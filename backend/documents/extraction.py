"""
Deterministic, local-only document extraction -- the foundation for the
Item 6 "Application Dossier" feature (docs/DJANGO_MIGRATION_PLAN.md
Phase 8 slice, porting _app/extract.py).

This module does the same three things the original did, and only
these three things:

1. Read the *text content* of a document (currently .pdf and .txt).
   Nothing here parses semantics ("what is the job title") -- that's a
   later, separate step (role_extract.py / applications/dossier.py).
   This is purely "get me the text."

2. Run cheap, regex-based extraction over that text: email addresses,
   phone numbers, and URLs. Deliberately conservative -- a missed
   contact is far better than a fabricated one (see documents/
   services.py's classify_doc_type, which carries the same
   best-guess-never-fabricate philosophy).

3. Run role_extract.extract_role_sections() and date_extract.
   extract_application_date() over that same text. Both run on ALL
   text unconditionally, not gated on doc_type -- gating would break
   the cache's content-hash-only key (the same content_hash must
   always produce the same cached result, regardless of which
   Document row first triggered extraction). Deciding *which* document
   in an application is the job posting, or whose detected date wins,
   is deferred to applications/dossier.py at assembly time.

Django-port difference from _app/extract.py: the original read bytes
off local disk via resolve_safe_for_root(root, relpath). There is no
local root any more (Phase 4 moved uploads to per-workspace S3-
compatible storage) -- this reads through Document.file.open()
instead, which works the same way whether that storage is local disk
(dev/test) or S3 (prod). Nothing in this file ever writes to storage;
it only reads document bytes and reads/writes the durable
DocumentExtraction cache, keyed by (workspace, content_hash) -- the
same content_hash Document already uses for duplicate detection.
Caching by content (not by Document row) means an identical resume
uploaded under two different applications is only ever extracted once
per workspace.

Bump EXTRACTOR_VERSION whenever the extraction logic changes in a way
that should invalidate previously cached results.
"""

from __future__ import annotations

import re

from django.utils import timezone

from . import date_extract, role_extract
from .models import Document, DocumentExtraction

# Carried over unchanged from _app/extract.py's EXTRACTOR_VERSION -- the
# cached shape (contacts + role sections + detected_date_applied) hasn't
# changed in this port, so existing cache rows (if any were ever written
# under the old app) would still be valid; a fresh Django deployment has
# no rows to invalidate either way.
EXTRACTOR_VERSION = "3"

SUPPORTED_TEXT_EXTENSIONS = {".pdf", ".txt"}


# --- text extraction ---------------------------------------------------------


def extract_text_from_document(document: Document) -> tuple[str, bool, str | None]:
    """Returns (text, ok, error). `ok=False` means extraction failed or
    the file type isn't supported yet -- never raises, so a single
    unreadable or encrypted PDF can't take down a batch/dossier
    operation. Reads through Document.file.open(), which works
    identically against local storage (dev/test) or S3 (prod) --
    see module docstring."""
    ext = (document.ext or "").lower()

    if ext == ".txt":
        try:
            with document.file.open("rb") as fh:
                raw = fh.read()
            return raw.decode("utf-8", errors="replace"), True, None
        except OSError as e:
            return "", False, str(e)

    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            from pypdf.errors import PdfReadError

            with document.file.open("rb") as fh:
                reader = PdfReader(fh)
                if reader.is_encrypted:
                    # Try an empty-password unlock (common for "owner
                    # password only" PDFs); if that fails, report it
                    # rather than crash.
                    try:
                        reader.decrypt("")
                    except Exception:
                        return "", False, "PDF is encrypted/password-protected"
                parts = []
                for page in reader.pages:
                    try:
                        parts.append(page.extract_text() or "")
                    except Exception:
                        continue  # one bad page shouldn't sink the whole document
                return "\n".join(parts), True, None
        except (PdfReadError, Exception) as e:  # noqa: BLE001 - deliberately broad, see docstring
            return "", False, str(e)

    return "", False, f"Unsupported file type for extraction: {ext or '(none)'}"


# --- deterministic contact extraction ----------------------------------------
# Ported unchanged from _app/extract.py -- pure regex/string logic, no
# filesystem dependency.

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Requires a real 10-digit US-style number (optional leading +1) so we don't
# false-positive on job IDs, zip+4 codes, or dates.
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}(?!\d)"
)

_URL_RE = re.compile(r"\bhttps?://[^\s<>\"')\]]+|\bwww\.[^\s<>\"')\]]+", re.I)

_TRAILING_PUNCT = ".,;:)]}\"'"


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def extract_emails(text: str) -> list[str]:
    found = [m.rstrip(_TRAILING_PUNCT) for m in _EMAIL_RE.findall(text)]
    return _dedupe_keep_order(found)


def extract_phones(text: str) -> list[str]:
    found = [m.strip() for m in _PHONE_RE.findall(text)]
    # Dedupe on digits-only so "(303) 555-1234" and "303-555-1234" collapse
    # to one entry even though the surface text differs.
    seen_digits = set()
    out = []
    for raw in found:
        digits = re.sub(r"\D", "", raw)
        if digits in seen_digits:
            continue
        seen_digits.add(digits)
        out.append(raw)
    return out


def extract_urls(text: str) -> list[str]:
    found = [m.rstrip(_TRAILING_PUNCT) for m in _URL_RE.findall(text)]
    return _dedupe_keep_order(found)


def extract_contacts(text: str) -> dict:
    return {
        "emails": extract_emails(text),
        "phones": extract_phones(text),
        "urls": extract_urls(text),
    }


# --- end-to-end extraction (uncached) ----------------------------------------


def extract_document(document: Document) -> dict:
    """Extraction result for one Document, freshly computed (no
    cache). Always returns a well-formed dict, even on failure -- see
    module docstring on why "not detected" beats an exception."""
    text, ok, error = extract_text_from_document(document)
    contacts = extract_contacts(text) if ok else {"emails": [], "phones": [], "urls": []}
    role_sections = (
        role_extract.extract_role_sections(text) if ok else role_extract.empty_role_sections()
    )
    detected_date_applied = date_extract.extract_application_date(text) if ok else None
    return {
        "extraction_ok": ok,
        "error": error,
        "text_length": len(text),
        **contacts,
        "detected_date_applied": detected_date_applied,
        **role_sections,
    }


# --- cached extraction (DocumentExtraction, keyed by content_hash) ----------


def get_or_extract(document: Document, force: bool = False) -> dict:
    """Same result as extract_document, but backed by the durable
    DocumentExtraction cache when the Document has a content_hash.
    A Document row with no content_hash (shouldn't normally happen --
    every upload computes one via documents/services.sha256_of) is
    always extracted fresh and never cached.

    A cache hit only counts if it was produced by the current
    EXTRACTOR_VERSION -- an older cached result from before a logic
    change is treated as a miss, not silently reused.
    """
    content_hash = document.content_hash
    if content_hash and not force:
        cached = (
            DocumentExtraction.objects.filter(
                workspace=document.workspace_id, content_hash=content_hash
            )
            .order_by("-extracted_at")
            .first()
        )
        if cached is not None and cached.extractor_version == EXTRACTOR_VERSION:
            return cached.extracted_json

    result = extract_document(document)
    if content_hash:
        DocumentExtraction.objects.update_or_create(
            workspace_id=document.workspace_id,
            content_hash=content_hash,
            defaults={
                "document": document,
                "extractor_version": EXTRACTOR_VERSION,
                "extracted_json": result,
                "extracted_at": timezone.now(),
            },
        )
    return result
