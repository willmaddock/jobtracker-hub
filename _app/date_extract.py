"""
Deterministic detection of an application/posting date from a document's
extracted text -- the backend half of the Item 6 "date-applied evidence
suggestion" (see ITEM6_DEV_LOG.tex's Checkpoint 4 Next Steps box).

Like role_extract.py, this module never fabricates a date: if no
recognizable pattern is found, it reports None, and the caller (dossier.py)
must never use that to silently overwrite a manually-set date_applied
override -- it's surfaced as an explicit accept/reject suggestion in the
UI instead.

This runs on ALL text unconditionally, not gated on classify.classify_doc_type()
-- same reasoning as role_extract.py: gating extraction on doc_type would
break the overrides.db extraction cache's path-independence guarantee
(keyed by content_hash alone). A resume or cover letter simply won't
contain a recognizable application-date pattern and reports None, same
outcome as "no pattern found" for any other document. Deciding *which*
document's detected date is worth surfacing (application_confirmation vs
job_posting) is deferred to dossier.py, at Dossier-assembly time -- same
split as the job-posting-pick logic.

Pattern was collected empirically from a real working tracker's documents
(114 application-related PDFs spot-checked), not guessed abstractly:

  Primary pattern -- email header line. Most application-confirmation
  documents in the wild are "Print to PDF" copies of an email, which
  carry the mail client's own header block at the top:

      From: no-reply@us.greenhouse-mail.io
      Subject: Thank you for applying to Extend
      Date: July 10, 2025 at 10:56 AM
      To: candidate@example.com

  That "Date:" line is the single most reliable signal available --
  it's the mail system's own timestamp for when the confirmation
  arrived, not a guess pulled from body prose. Some sources (e.g. a
  browser's "print" of a Gmail thread) repeat the "Date:" label
  ("Date: Date: Date: Jul 30, 2025") or use an abbreviated month
  ("Jul 30, 2025") instead of the full name -- both are handled by the
  same pattern. The trailing "at H:MM AM/PM" is optional and ignored;
  only the calendar date is extracted, since that's all date_applied
  stores.

  Fallback pattern -- keyworded numeric date. Some ATS confirmation
  emails (schooljobs.com, governmentjobs.com) restate the same
  timestamp inline in the body instead of (or in addition to) an email
  header, e.g. "Your application has been received by Front Range
  Community College for the Part-Time Professional Tester position at
  09/24/2025 06:00 PM Mountain Time" -- real corpus text where the verb
  and the date are ~90 characters apart. This is only trusted within a
  short window (120 chars, never crossing a sentence boundary) after
  one of a small set of application-received verbs, to avoid matching
  an unrelated MM/DD/YYYY elsewhere in the document (a job ID, a
  posting's own date, etc).

Bump DATE_EXTRACTOR_VERSION (and extract.py's EXTRACTOR_VERSION, which
wraps this) whenever this logic changes in a way that should invalidate
previously cached results.
"""

from __future__ import annotations

import re
from datetime import date

DATE_EXTRACTOR_VERSION = "1"

_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

# "Date: July 10, 2025 at 10:56 AM" / "Date: Date: Date: Jul 30, 2025"
# (repeated label and abbreviated-vs-full month both seen in real
# corpus). The "at ..." time suffix is not captured -- only the date.
_EMAIL_HEADER_DATE_RE = re.compile(
    r"(?im)^(?:Date:\s*)+([A-Za-z]{3,9})\.?\s+(\d{1,2}),\s*(\d{4})\b"
)

# Verbs an application-received notice actually uses, immediately
# (within a short window) followed by a numeric MM/DD/YYYY date --
# conservative on purpose so we don't match a job ID or a posting date
# found elsewhere in the same document.
_KEYWORD_SLASH_DATE_RE = re.compile(
    r"(?is)\b(?:received|submitted|applied)\b[^.\n]{0,120}?\b(\d{1,2})/(\d{1,2})/(\d{4})\b"
)


def _to_iso(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None  # e.g. a false-positive "13/45/2025" style match


def extract_application_date(text: str) -> str | None:
    """Best-effort ISO ``YYYY-MM-DD`` extracted from `text`, or None if no
    recognized pattern is found. Never raises, never guesses -- see
    module docstring for the two patterns tried, in priority order."""
    if not text:
        return None

    m = _EMAIL_HEADER_DATE_RE.search(text)
    if m:
        month_name, day_s, year_s = m.groups()
        month = _MONTHS.get(month_name.lower())
        if month:
            iso = _to_iso(int(year_s), month, int(day_s))
            if iso:
                return iso

    m = _KEYWORD_SLASH_DATE_RE.search(text)
    if m:
        month_s, day_s, year_s = m.groups()
        iso = _to_iso(int(year_s), int(month_s), int(day_s))
        if iso:
            return iso

    return None
