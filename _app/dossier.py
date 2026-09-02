"""
Application Dossier assembly (Checkpoint 3).

Combines Checkpoint 1's contact extraction and Checkpoint 2's role-section
extraction into a single per-application payload, by running
extract.get_or_extract() over every document already grouped under one
application folder (db.load_documents()'s output).

The job-posting-within-a-folder heuristic lives HERE, at the API/assembly
layer, not inside extract.py -- see ITEM6_DEV_LOG.tex's Checkpoint 2 "Next
Steps" box for why. A folder can hold several PDFs (job posting,
application-received confirmation, a resume, a cover letter); only ONE of
them should populate the four role sections. classify.classify_doc_type()
already tags that document as "job_posting" by filename at index time
(overridable later via doc_type_override, hence we key off
`effective_doc_type` rather than the raw `doc_type`) -- this module just
picks which one, deterministically, when there's more than one candidate.

Tiebreak rule when multiple documents in the folder are classified as
"job_posting": pick the one whose `relpath` sorts first alphabetically.
This is an arbitrary but fully deterministic rule (same folder contents
always yield the same choice, including across a jobtracker.db rebuild).
See test_dossier.py for the case this covers.

Contacts, by contrast, are aggregated (deduped) across EVERY document in
the folder, not just the job posting -- a recruiter's email/phone often
only appears on the posting itself, while the candidate's own contact
info lives on the resume or cover letter. Deduping follows the same
rules extract.py already uses per-document (case-insensitive for
emails/URLs, digits-only for phones), just applied across the merged
set instead of within one document's text.

Nothing here writes to the JobTracker folder or to overrides.db directly
-- all writes happen inside extract.get_or_extract()'s existing
content-hash-keyed cache. A document that fails to extract (unreadable,
encrypted, unsupported type) is skipped for contacts/role-sections and
reported in `extraction_errors`, rather than failing the whole Dossier.

Checkpoint 5 adds date-applied evidence: date_extract.py's per-document
`detected_date_applied` is picked here the same way job_posting_relpath
is -- deterministic, at the assembly layer, never inside extract.py.
`application_confirmation` documents are checked before `job_posting`
documents (in that priority order, alphabetically-first-by-relpath
within each), because a confirmation email's own timestamp is a direct
record of when the application was submitted, while a job posting's
text at best names when the position was *listed*. This is only ever
surfaced as a suggestion (`detected_date_applied` /
`detected_date_source_relpath` in the returned dict) -- this module
never writes to the `date_applied` override itself; that stays the API
layer's job (api.py's application_dossier endpoint), which is also
where the auto-fill-vs-suggest decision is made.

Checkpoint 6 adds `detected_date_evidence_tier` ("confirmation" or
"posting", None when nothing was detected) alongside the two fields
above, so the API layer can tell which kind of evidence won without
re-deriving it from DATE_EVIDENCE_DOC_TYPES itself. Confirmation-email
evidence is strong enough to auto-fill an empty date_applied silently;
job-posting evidence is not (it names when the position was *listed*,
not when you applied) and stays a click-required suggestion. See
api.py's application_dossier for exactly how the tier is used.

Item 7 adds `timeline_events`: one entry per application_confirmation or
interview_notice document that has a detected date (see
docs/specs/ITEM7_TIMELINE_FDD_DRAFT.md's "v1 scope" -- built from real-corpus
evidence, not the abstract 6-stage event list originally proposed).
Unlike `detected_date_applied` above, this is NOT a single winner-take-all
value -- every matching document becomes its own event (e.g. a phone
screen request AND a later interview request in the same folder both
show up), because collapsing them would hide real information the
documents actually contain. This reuses the exact same per-document
`detected_date_applied` extract.py already computes for every doc
regardless of type -- no new extraction logic. Rejection is deliberately
NOT a doc-derived event here (the real corpus has effectively no
rejection documents); it's surfaced instead via the item-level "Current
status" entry that api.py's application_dossier adds alongside this list,
using overrides_store.py's status_history log rather than a document.
"""

from __future__ import annotations

import re
from pathlib import Path

import extract
import role_extract

# Priority order for whose detected_date_applied gets surfaced when more
# than one document has one -- see module docstring for why confirmation
# beats posting. Ties within a doc type are broken alphabetically by
# relpath, same deterministic rule job_posting_candidates already uses.
DATE_EVIDENCE_DOC_TYPES = ("application_confirmation", "job_posting")

# Item 7: doc types that can each anchor their own Timeline event, and the
# order used to break ties when two events land on the same date --
# "Applied" reads naturally before "Interview scheduled" for a same-day
# confirmation + notice, and it's a fully deterministic tiebreak either
# way (see test_timeline.py).
TIMELINE_EVENT_DOC_TYPES = ("application_confirmation", "interview_notice")
_TIMELINE_TYPE_ORDER = {doc_type: i for i, doc_type in enumerate(TIMELINE_EVENT_DOC_TYPES)}


def _dedupe_emails_urls(existing_keys: set[str], out: list[str], values: list[str]) -> None:
    for v in values:
        key = v.lower()
        if key not in existing_keys:
            existing_keys.add(key)
            out.append(v)


def _dedupe_phones(existing_keys: set[str], out: list[str], values: list[str]) -> None:
    for v in values:
        key = re.sub(r"\D", "", v)
        if key not in existing_keys:
            existing_keys.add(key)
            out.append(v)


def assemble_dossier(ov_conn, root: Path, docs: list[dict]) -> dict:
    """`docs` is the list already produced by db.load_documents() for one
    application, so each entry carries `relpath`, `content_hash`, and
    `effective_doc_type`. Never raises -- a folder with no documents, or
    where every document fails to extract, still returns a well-formed
    dossier: empty contact lists and every role section as
    role_extract.NOT_DETECTED ("Not detected"), never fabricated or
    substituted with an empty string/null. That "Not detected" value is
    passed straight through end-to-end, exactly as extract.py/
    role_extract.py already produce it. `detected_date_applied` /
    `detected_date_source_relpath` are None/None when no document in the
    folder yields a recognizable date -- see date_extract.py.
    """
    job_posting_candidates = sorted(
        d["relpath"] for d in docs if d.get("effective_doc_type") == "job_posting"
    )
    job_posting_relpath = job_posting_candidates[0] if job_posting_candidates else None

    emails: list[str] = []
    phones: list[str] = []
    urls: list[str] = []
    seen_emails: set[str] = set()
    seen_phones: set[str] = set()
    seen_urls: set[str] = set()

    role_sections = role_extract.empty_role_sections()
    extraction_errors: list[dict] = []
    # One list of (relpath, detected_date) per doc type in
    # DATE_EVIDENCE_DOC_TYPES, so we can pick the alphabetically-first
    # relpath within the highest-priority doc type that had any hit.
    date_candidates: dict[str, list[tuple[str, str]]] = {
        doc_type: [] for doc_type in DATE_EVIDENCE_DOC_TYPES
    }
    # Item 7: every application_confirmation/interview_notice document with
    # a detected date becomes its own timeline event -- never merged, even
    # when a folder has more than one interview_notice document.
    timeline_events: list[dict] = []

    for d in docs:
        result = extract.get_or_extract(ov_conn, root, d["relpath"], d.get("content_hash"))
        if not result.get("extraction_ok"):
            extraction_errors.append({"relpath": d["relpath"], "error": result.get("error")})
            continue

        _dedupe_emails_urls(seen_emails, emails, result.get("emails", []))
        _dedupe_phones(seen_phones, phones, result.get("phones", []))
        _dedupe_emails_urls(seen_urls, urls, result.get("urls", []))

        if d["relpath"] == job_posting_relpath:
            for key in role_extract.SECTION_KEYS:
                role_sections[key] = result.get(key, role_extract.NOT_DETECTED)

        effective_doc_type = d.get("effective_doc_type")
        detected_date = result.get("detected_date_applied")
        if detected_date and effective_doc_type in date_candidates:
            date_candidates[effective_doc_type].append((d["relpath"], detected_date))
        if detected_date and effective_doc_type in TIMELINE_EVENT_DOC_TYPES:
            timeline_events.append(
                {"date": detected_date, "doc_type": effective_doc_type, "relpath": d["relpath"]}
            )

    timeline_events.sort(
        key=lambda e: (e["date"], _TIMELINE_TYPE_ORDER.get(e["doc_type"], 99), e["relpath"])
    )

    detected_date_applied = None
    detected_date_source_relpath = None
    detected_date_evidence_tier = None
    for doc_type in DATE_EVIDENCE_DOC_TYPES:
        candidates = sorted(date_candidates[doc_type])
        if candidates:
            detected_date_source_relpath, detected_date_applied = candidates[0]
            detected_date_evidence_tier = (
                "confirmation" if doc_type == "application_confirmation" else "posting"
            )
            break

    return {
        "job_posting_relpath": job_posting_relpath,
        "job_posting_candidates": job_posting_candidates,
        "contacts": {"emails": emails, "phones": phones, "urls": urls},
        "extraction_errors": extraction_errors,
        "detected_date_applied": detected_date_applied,
        "detected_date_source_relpath": detected_date_source_relpath,
        "detected_date_evidence_tier": detected_date_evidence_tier,
        "timeline_events": timeline_events,
        **role_sections,
    }
