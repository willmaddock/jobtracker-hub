"""Read-only dossier projection of previously extracted eligible evidence."""
from __future__ import annotations

import re

from documents import role_extract
from documents.extraction import get_cached_extraction
from documents.services import effective_doc_type

# Confirmation has priority over a posting suggestion; conflicting dates have
# no winner. Filename order only selects a representative of an agreeing date.
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
    # DATE_EVIDENCE_DOC_TYPES, retaining agreement/conflict before selecting
    # a representative supporting Document.
    date_candidates: dict[str, list[tuple[str, int, str]]] = {
        doc_type: [] for doc_type in DATE_EVIDENCE_DOC_TYPES
    }
    # Every application_confirmation/interview_notice document with a
    # detected date becomes its own timeline event -- never merged,
    # even when an application has more than one interview_notice
    # document.
    timeline_events: list[dict] = []

    conflicting_confirmation = False
    for d in documents:
        result = get_cached_extraction(d)
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
        if doc_type == "application_confirmation" and result.get("date_evidence", {}).get("state") == "conflicted":
            conflicting_confirmation = True
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
            if len({candidate[2] for candidate in candidates}) > 1:
                detected_date_evidence_tier = "conflicted"
                break
            filename, document_id, detected_date_applied = candidates[0]
            detected_date_source_document_id = document_id
            detected_date_evidence_tier = (
                "confirmation" if doc_type == "application_confirmation" else "posting"
            )
            break

    if conflicting_confirmation:
        detected_date_applied = None
        detected_date_source_document_id = None
        detected_date_evidence_tier = "conflicted"

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
