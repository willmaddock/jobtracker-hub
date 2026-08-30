"""
Deterministic, header-pattern-based splitting of job-posting text into four
sections: Role Summary, Duties, Required Qualifications, Preferred
Qualifications.

This module takes over where extract.py's extract_text_from_file() leaves
off: given the raw text pypdf already pulled from a document, it tries to
locate the standard section headers real job postings use and slices the
text between them. Nothing here fabricates content — a section whose
header can't be found reports NOT_DETECTED, never a guess.

Header phrasing was collected empirically by inspecting ~20 real job
postings across corporate career sites (Kroger, AWS, CoBank, EchoStar,
InterTek, BET365, ...) and Colorado public-sector "Job Bulletin" postings
(Metro Water Recovery, Adams County, Dept of Revenue, Commerce City,
FRCC) rather than guessed abstractly. Examples of headers actually seen,
by category:

  role_summary:               "Job Description", "Description",
                               "General Summary", "General Purpose",
                               "Who You Are", "What are we looking for?",
                               "What Success Looks Like In This Job"
  duties:                     "Responsibilities", "Essential Functions",
                               "Essential Duties & Responsibilities",
                               "Examples of Duties",
                               "Job Duties and Responsibilities",
                               "Primary Duties", "What You'll Do",
                               "Examples of Duties for Success"
  required_qualifications:    "Qualifications", "Requirements",
                               "Basic Qualifications",
                               "Minimum Requirements & Qualifications",
                               "Skills, Experience and Requirements",
                               "Qualifications for Success"
  preferred_qualifications:   "Preferred Qualifications", "Desired",
                               "Nice To Have", "Preferred Skills and
                               Experience"

Two real-corpus PDF-rendering quirks are normalized before matching:
  - Typographic ligatures ("Qualiﬁcations" -> "Qualifications") that pypdf
    sometimes leaves un-decoded.
  - A duplicated-header artifact from some career-site templates, where
    the header text is repeated back-to-back with no separator
    ("Job DescriptionJob DescriptionJob Description").

Some real postings additionally nest a Minimum/Desired split inside a
single "Qualifications" header (Kroger is the clearest example: one
"QUALIFICATIONS" header, then a bare "Minimum" line, then a bare
"Desired" line). Both bare labels are recognized: "Desired" (along with
"Preferred"/"Nice To Have") is itself a preferred_qualifications header,
so it naturally creates the split; "Minimum"/"Basic"/"Required" are bare
filler labels that get stripped out of the surrounding section text
rather than left in as noise.
"""

from __future__ import annotations

import re

# --- public constants ---------------------------------------------------

ROLE_SUMMARY = "role_summary"
DUTIES = "duties"
REQUIRED_QUALIFICATIONS = "required_qualifications"
PREFERRED_QUALIFICATIONS = "preferred_qualifications"

SECTION_KEYS = [ROLE_SUMMARY, DUTIES, REQUIRED_QUALIFICATIONS, PREFERRED_QUALIFICATIONS]

NOT_DETECTED = "Not detected"

# --- header vocabulary (collected from the real corpus, see module docstring) --

_ROLE_SUMMARY_HEADERS = {
    "job description",
    "description",
    "general summary",
    "general purpose",
    "role summary",
    "job summary",
    "position summary",
    "overview",
    "about the role",
    "about this role",
    "who you are",
    "what are we looking for",
    "what success looks like in this job",
}

_DUTIES_HEADERS = {
    "responsibilities",
    "duties",
    "duties and responsibilities",
    "essential functions",
    "essential duties & responsibilities",
    "essential duties and responsibilities",
    "examples of duties",
    "job duties and responsibilities",
    "primary duties",
    "key responsibilities",
    "what you'll do",
    "what you will be doing",
    "examples of duties for success",
}

_REQUIRED_QUALIFICATIONS_HEADERS = {
    "qualifications",
    "requirements",
    "minimum qualifications",
    "basic qualifications",
    "required qualifications",
    "minimum requirements & qualifications",
    "minimum requirements and qualifications",
    "skills, experience and requirements",
    "knowledge, skills and abilities",
    "knowledge/skills/abilities",
    "what you'll need",
    "what you bring",
    "qualifications for success",
}

_PREFERRED_QUALIFICATIONS_HEADERS = {
    "preferred qualifications",
    "desired qualifications",
    "desired",
    "nice to have",
    "preferred skills and experience",
    "preferred",
}

_HEADER_TO_CATEGORY: dict[str, str] = {}
for _phrase in _ROLE_SUMMARY_HEADERS:
    _HEADER_TO_CATEGORY[_phrase] = ROLE_SUMMARY
for _phrase in _DUTIES_HEADERS:
    _HEADER_TO_CATEGORY[_phrase] = DUTIES
for _phrase in _REQUIRED_QUALIFICATIONS_HEADERS:
    _HEADER_TO_CATEGORY[_phrase] = REQUIRED_QUALIFICATIONS
for _phrase in _PREFERRED_QUALIFICATIONS_HEADERS:
    _HEADER_TO_CATEGORY[_phrase] = PREFERRED_QUALIFICATIONS

# Bare labels that show up nested inside a "Qualifications" section (the
# Kroger pattern) and should be stripped from the section text rather than
# treated as their own boundary or left in as noise. "desired"/"preferred"/
# "nice to have" are NOT here -- they're real category headers above, and
# stripping happens naturally because slicing starts *after* the header line.
_FILLER_LABELS = {"minimum", "basic", "required"}

# --- text normalization ---------------------------------------------------

_LIGATURES = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
}

_CURLY_QUOTES = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
}


def _normalize_chars(s: str) -> str:
    for lig, plain in _LIGATURES.items():
        s = s.replace(lig, plain)
    for curly, straight in _CURLY_QUOTES.items():
        s = s.replace(curly, straight)
    return s


# A line that is just some short phrase repeated back-to-back with no
# separator, e.g. "Job DescriptionJob DescriptionJob Description". Career
# sites render duplicated nav/header text like this often enough in the
# real corpus that it's worth collapsing before header matching.
_DUPLICATED_RE = re.compile(r"^(.{3,60}?)(?:\1)+$")


def _collapse_duplicated(line: str) -> str:
    m = _DUPLICATED_RE.match(line)
    return m.group(1) if m else line


def _header_key(line: str) -> str:
    """Normalize a line down to the form used for header-phrase lookup:
    ligatures/curly-quotes fixed, duplicated-header artifact collapsed,
    trailing colon/question-mark stripped, case-folded."""
    norm = _normalize_chars(line).strip()
    norm = _collapse_duplicated(norm).strip()
    norm = norm.rstrip(":?").strip()
    return norm.lower()


# --- core extraction --------------------------------------------------------

def empty_role_sections() -> dict:
    """The all-NOT_DETECTED shape, used by extract.py when extraction
    itself failed (no text to search headers in)."""
    return {key: NOT_DETECTED for key in SECTION_KEYS}


def _strip_filler_lines(content: str) -> str:
    lines = content.split("\n")
    kept = [ln for ln in lines if _header_key(ln) not in _FILLER_LABELS]
    cleaned = "\n".join(kept).strip()
    return re.sub(r"\n{3,}", "\n\n", cleaned)


def extract_role_sections(text: str) -> dict:
    """Split `text` into role_summary / duties / required_qualifications /
    preferred_qualifications using header-pattern matching. Any section
    whose header isn't found reports NOT_DETECTED -- never fabricated.
    Only the FIRST occurrence of a given category's header counts; a
    document that happens to repeat a header (e.g. two "Responsibilities"
    blocks in unrelated sections) keeps only the first block for that
    category rather than concatenating both.
    """
    if not text:
        return empty_role_sections()

    # Walk lines, tracking character offsets so we can slice the original
    # text (not the normalized copy) between header boundaries. Record
    # EVERY header line found (not deduplicated) -- a section's content
    # must stop at the *next* header line of any kind, including a repeat
    # of its own category, or a later unrelated "Responsibilities" block
    # would get appended onto an earlier one instead of being ignored.
    all_matches: list[tuple[int, int, str]] = []  # (line_start, line_end, category)
    offset = 0
    for line in text.split("\n"):
        line_start = offset
        line_end = offset + len(line)
        offset = line_end + 1  # account for the '\n' split() consumed

        key = _header_key(line)
        category = _HEADER_TO_CATEGORY.get(key)
        if category:
            all_matches.append((line_start, line_end, category))

    if not all_matches:
        return empty_role_sections()

    result = empty_role_sections()
    seen_categories: set[str] = set()
    for i, (_, line_end, category) in enumerate(all_matches):
        if category in seen_categories:
            continue  # only the first occurrence of a category counts
        seen_categories.add(category)
        section_end = all_matches[i + 1][0] if i + 1 < len(all_matches) else len(text)
        raw = text[line_end:section_end]
        cleaned = _strip_filler_lines(raw)
        result[category] = cleaned if cleaned else NOT_DETECTED

    return result
