"""
Deterministic, local-only document extraction — the foundation for the
Item 6 "Application Dossier" feature.

This module does two things, and only these two things:

1. Read the *text content* of a document (currently .pdf and .txt) off
   disk. Nothing here parses semantics ("what is the job title") — that's
   a later, separate step. This is purely "get me the text."

2. Run cheap, regex-based extraction over that text: email addresses,
   phone numbers, and URLs. These are deliberately conservative — a
   missed contact is far better than a fabricated one (see classify.py's
   own philosophy: best-guess, easy to correct, never silently wrong).

3. Run role_extract.extract_role_sections() over that same text: header-
   pattern-based splitting into role_summary / duties /
   required_qualifications / preferred_qualifications. This runs on ALL
   text unconditionally, not gated on classify.classify_doc_type() —
   gating it would break the cache's path-independence guarantee (the
   same content_hash must always produce the same cached result,
   regardless of which filename/path first triggered extraction). A
   non-job-posting document simply won't contain these headers and
   reports "Not detected" for all four fields, same as any other
   document with no recognizable headers. Deciding *which* document in a
   folder is the job posting is deferred to the API layer, at Dossier-
   assembly time.

Nothing in this file ever writes to the JobTracker folder. It only reads
document bytes for extraction and (via get_or_extract) reads/writes the
durable extraction cache in overrides.db, keyed by content_hash — the
same hash documents.content_hash already uses for duplicate detection.
Caching by content (not by path) means an identical resume filed under
two different applications is only ever extracted once, and the cache
survives a jobtracker.db rebuild since it lives in overrides.db.

Bump EXTRACTOR_VERSION whenever the extraction logic changes in a way
that should invalidate previously cached results.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import date_extract
import overrides_store as ov
import role_extract

# Bumped to "3" for the Checkpoint 5 date_extract.py addition (new
# detected_date_applied field in the extraction result) -- any result
# cached under the old shape is treated as a miss, not silently reused.
EXTRACTOR_VERSION = "3"

# --- text extraction ---------------------------------------------------------

SUPPORTED_TEXT_EXTENSIONS = {".pdf", ".txt"}


def resolve_safe_for_root(root: Path, relpath: str) -> Path:
    """Same defense-in-depth guarantee as api.py's resolve_safe, but kept
    dependency-free (no FastAPI import) so this module can be used from
    tests, scripts, or the API layer alike. Raises ValueError instead of
    HTTPException — callers in api.py should translate that themselves.
    """
    root = root.resolve()
    full = (root / relpath).resolve()
    try:
        full.relative_to(root)
    except ValueError:
        raise ValueError(f"Path escapes JobTracker root: {relpath}")
    if not full.exists() or not full.is_file():
        raise ValueError(f"File not found: {relpath}")
    return full


def extract_text_from_file(path: Path) -> tuple[str, bool, str | None]:
    """Returns (text, ok, error). `ok=False` means extraction failed or the
    file type isn't supported yet — never raises, so a single unreadable
    or encrypted PDF can't take down a batch/dossier operation."""
    ext = path.suffix.lower()
    if ext == ".txt":
        try:
            return path.read_text(encoding="utf-8", errors="replace"), True, None
        except OSError as e:
            return "", False, str(e)

    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            from pypdf.errors import PdfReadError

            reader = PdfReader(str(path))
            if reader.is_encrypted:
                # Try an empty-password unlock (common for "owner password
                # only" PDFs); if that fails, report it rather than crash.
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

def extract_document(root: Path, relpath: str) -> dict:
    """Extraction result for one document, freshly computed (no cache).
    Always returns a well-formed dict, even on failure — see module
    docstring on why "not detected" beats an exception."""
    try:
        full = resolve_safe_for_root(root, relpath)
    except ValueError as e:
        return {
            "extraction_ok": False,
            "error": str(e),
            "text_length": 0,
            "emails": [],
            "phones": [],
            "urls": [],
            "detected_date_applied": None,
            **role_extract.empty_role_sections(),
        }

    text, ok, error = extract_text_from_file(full)
    contacts = extract_contacts(text) if ok else {"emails": [], "phones": [], "urls": []}
    role_sections = role_extract.extract_role_sections(text) if ok else role_extract.empty_role_sections()
    detected_date_applied = date_extract.extract_application_date(text) if ok else None
    return {
        "extraction_ok": ok,
        "error": error,
        "text_length": len(text),
        **contacts,
        "detected_date_applied": detected_date_applied,
        **role_sections,
    }


# --- cached extraction (overrides.db, keyed by content_hash) ----------------

def get_or_extract(
    ov_conn,
    root: Path,
    relpath: str,
    content_hash: str | None,
    force: bool = False,
) -> dict:
    """Same result as extract_document, but backed by the durable
    document_extractions cache in overrides.db when a content_hash is
    available. Documents without a content_hash (unreadable at index
    time) are always extracted fresh and never cached.

    A cache hit only counts if it was produced by the current
    EXTRACTOR_VERSION — an older cached result from before a logic change
    is treated as a miss, not silently reused.
    """
    if content_hash and not force:
        cached = ov.get_extraction(ov_conn, content_hash)
        if cached and cached.get("extractor_version") == EXTRACTOR_VERSION:
            return json.loads(cached["extracted_json"])

    result = extract_document(root, relpath)
    if content_hash:
        ov.set_extraction(ov_conn, content_hash, EXTRACTOR_VERSION, result)
    return result
