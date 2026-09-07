"""
Application Dossier assembly (docs/DJANGO_MIGRATION_PLAN.md Phase 8
slice, porting _app/dossier.py's assemble_dossier()).

Combines documents/extraction.py's contact extraction and role-section
extraction into a single per-application payload, by running
extraction.get_or_extract() over every Document already belonging to
one Application.

The job-posting-within-an-application heuristic lives HERE, at the
assembly layer, not inside documents/extraction.py -- same split the
original kept between dossier.py and extract.py. An application can
have several documents (job posting, application-received
confirmation, a resume, a cover letter); only ONE of them should
populate the four role sections. documents/services.effective_doc_type()
already resolves doc_type_override vs the classifier's own doc_type --
this module just picks which document, deterministically, when more
than one is classified "job_posting".

Django-port identity change: the original keyed everything (tiebreaks,
extraction_errors, timeline_events) off `relpath`, a folder-relative
path string. There is no relpath any more -- Document.id is the real
identity (same numeric-id-over-string-key choice documents/
serializers.py and applications/views.py already made). Tiebreaks that
used to sort by relpath now sort by (filename, id) for the same
"fully deterministic, same inputs always yield the same choice"
guarantee; every place the original surfaced a relpath now surfaces
`document_id` (plus `filename` where it aids display).

Contacts are aggregated (deduped) across EVERY document belonging to
the application, not just the job posting -- a recruiter's email/phone
often only appears on the posting itself, while the candidate's own
contact info lives on the resume or cover letter. Deduping follows the
same rules documents/extraction.py already uses per-document
(case-insensitive for emails/URLs, digits-only for phones), just
applied across the merged set instead of within one document's text.

Nothing here writes anything -- all writes happen inside
extraction.get_or_extract()'s existing content-hash-keyed cache. A
document that fails to extract (unreadable, encrypted, unsupported
type) is skipped for contacts/role-sections and reported in
`extraction_errors`, rather than failing the whole Dossier.

detected_date_applied / detected_date_source_document_id /
detected_date_evidence_tier: date_extract.py's per-document
`detected_date_applied` is picked here the same way job_posting_document_id
is -- deterministic, at the assembly layer, never inside
documents/extraction.py. `application_confirmation` documents are
checked before `job_posting` documents (in that priority order,
tied within each doc type by (filename, id)), because a confirmation
email's own timestamp is a direct record of when the application was
submitted, while a job posting's text at best names when the position
was *listed*. This module never writes to Override.date_applied
itself -- see applications/views.py's dossier action, which owns the
auto-fill-vs-suggest decision, matching the original's api.py split.

timeline_events: one entry per application_confirmation or
interview_notice document that has a detected date. Unlike
detected_date_applied above, this is NOT a single winner-take-all
value -- every matching document becomes its own event (e.g. a phone
screen request AND a later interview request on the same application
both show up), because collapsing them would hide real information the
documents actually contain.
"""

from __future__ import annotations

import re

from documents import role_extract
from documents.extraction import get_or_extract
from documents.services import effective_doc_type

# Priority order for whose detected_date_applied gets surfaced when more
# than one document has one -- see module docstring for why confirmation
# beats posting. Ties within a doc type are broken by (filename, id),
# same deterministic rule job_posting_candidates already uses.
DATE_EVIDENCE_DOC_TYPES = ("application_confirmation", "job_posting")

# Doc types that can each anchor their own Timeline event, and the
# order used to break ties when two events land on the same date --
# "Applied" reads naturally before "Interview scheduled" for a same-day
# confirmation + notice, and it's a fully deterministic tiebreak either
# way.
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


def assemble_dossier(documents) -> dict:
    """`documents` is an iterable of Document rows already belonging
    to one Application (see applications/views.py's dossier action --
    pass `application.documents.select_related("override")` so
    effective_doc_type() doesn't issue one query per document). Never
    raises -- an application with no documents, or where every
    document fails to extract, still returns a well-formed dossier:
    empty contact lists and every role section as
    role_extract.NOT_DETECTED ("Not detected"), never fabricated or
    substituted with an empty string/null. That "Not detected" value
    is passed straight through end-to-end, exactly as documents/
    extraction.py / role_extract.py already produce it.
    detected_date_applied / detected_date_source_document_id are
    None/None when no document yields a recognizable date.
    """
    documents = list(documents)

    job_posting_candidates = sorted(
        (d for d in documents if effective_doc_type(d) == "job_posting"),
        key=lambda d: (d.filename, d.id),
    )
    job_posting_document_id = job_posting_candidates[0].id if job_posting_candidates else None

    emails: list[str] = []
    phones: list[str] = []
    urls: list[str] = []
    seen_emails: set[str] = set()
    seen_phones: set[str] = set()
    seen_urls: set[str] = set()

    role_sections = role_extract.empty_role_sections()
    extraction_errors: list[dict] = []
    # One list of (filename, id, detected_date) per doc type in
    # DATE_EVIDENCE_DOC_TYPES, so we can pick the (filename, id)-first
    # document within the highest-priority doc type that had any hit.
    date_candidates: dict[str, list[tuple[str, int, str]]] = {
        doc_type: [] for doc_type in DATE_EVIDENCE_DOC_TYPES
    }
    # Every application_confirmation/interview_notice document with a
    # detected date becomes its own timeline event -- never merged,
    # even when an application has more than one interview_notice
    # document.
    timeline_events: list[dict] = []

    for d in documents:
        result = get_or_extract(d)
        if not result.get("extraction_ok"):
            extraction_errors.append(
                {"document_id": d.id, "filename": d.filename, "error": result.get("error")}
            )
            continue

        _dedupe_emails_urls(seen_emails, emails, result.get("emails", []))
        _dedupe_phones(seen_phones, phones, result.get("phones", []))
        _dedupe_emails_urls(seen_urls, urls, result.get("urls", []))

        if d.id == job_posting_document_id:
            for key in role_extract.SECTION_KEYS:
                role_sections[key] = result.get(key, role_extract.NOT_DETECTED)

        doc_type = effective_doc_type(d)
        detected_date = result.get("detected_date_applied")
        if detected_date and doc_type in date_candidates:
            date_candidates[doc_type].append((d.filename, d.id, detected_date))
        if detected_date and doc_type in TIMELINE_EVENT_DOC_TYPES:
            timeline_events.append(
                {
                    "date": detected_date,
                    "doc_type": doc_type,
                    "document_id": d.id,
                    "filename": d.filename,
                }
            )

    timeline_events.sort(
        key=lambda e: (e["date"], _TIMELINE_TYPE_ORDER.get(e["doc_type"], 99), e["filename"], e["document_id"])
    )

    detected_date_applied = None
    detected_date_source_document_id = None
    detected_date_evidence_tier = None
    for doc_type in DATE_EVIDENCE_DOC_TYPES:
        candidates = sorted(date_candidates[doc_type])
        if candidates:
            filename, document_id, detected_date_applied = candidates[0]
            detected_date_source_document_id = document_id
            detected_date_evidence_tier = (
                "confirmation" if doc_type == "application_confirmation" else "posting"
            )
            break

    return {
        "job_posting_document_id": job_posting_document_id,
        "job_posting_candidates": [d.id for d in job_posting_candidates],
        "contacts": {"emails": emails, "phones": phones, "urls": urls},
        "extraction_errors": extraction_errors,
        "detected_date_applied": detected_date_applied,
        "detected_date_source_document_id": detected_date_source_document_id,
        "detected_date_evidence_tier": detected_date_evidence_tier,
        "timeline_events": timeline_events,
        **role_sections,
    }
