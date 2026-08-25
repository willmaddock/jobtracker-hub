"""
Classification heuristics for JobTracker.

Two jobs:
1. Map a top-level folder name (e.g. "Certifications", "Applications") to a
   `section` — the broad bucket it belongs to in the hub.
2. Map an individual filename (e.g. "coverletter.pdf") to a `doc_type`.

Both are heuristic and filename-based (no PDF content parsing) so they run
fast over hundreds of files and are easy for you to correct later from the
app if a file gets misclassified. Manual corrections (status overrides,
company merges, notes) live in overrides_store.py / overrides.db, never
here — this file only has the automatic, best-guess rules.

CUSTOMIZING FOR YOUR OWN FOLDERS
---------------------------------
The section-mapping rules and the "nested application" special case (for
government/compliance folders that bundle real job applications inside a
dated subfolder structure) are NOT hardcoded here — they're loaded from
`classify_config.json`, which sits next to this file. Edit that file to
match your own folder names; nothing in this module needs to change.
Set the JOBTRACKER_CLASSIFY_CONFIG environment variable to point at a
different config file if you'd rather keep it outside the repo entirely
(handy if you're running this against a private fork).
"""

import json
import os
import re
from pathlib import Path

# --- Load user-editable config ---------------------------------------------
_CONFIG_ENV_VAR = "JOBTRACKER_CLASSIFY_CONFIG"
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "classify_config.json"

# Generic fallback rules, used only if classify_config.json is missing or
# unreadable — so the app still runs sensibly out of the box even without
# the config file present.
_FALLBACK_SECTION_RULES = [
    (r"^applications$", "applications"),
    (r"^certifications?$", "credentials"),
    (r"^(degree|transcripts?)", "credentials"),
    (r"^references?$", "network"),
    (r"^(people|contacts)$", "network"),
    (r"^resume library", "resume_library"),
    (r"^(solicited|master) resume", "resume_library"),
    (r"^leads$", "leads"),
    (r"^case management$", "compliance"),
]


def _load_config() -> dict:
    path = Path(os.environ.get(_CONFIG_ENV_VAR, _DEFAULT_CONFIG_PATH))
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


_CONFIG = _load_config()

# --- Section mapping -------------------------------------------------------
# Top-level folder name -> section. Matching is case-insensitive and by
# substring, so small naming variations still map correctly. Sourced from
# classify_config.json's "section_rules"; falls back to the generic list
# above if the config file is missing.
_raw_section_rules = _CONFIG.get("section_rules")
if _raw_section_rules:
    SECTION_RULES = [
        (re.compile(rule["pattern"], re.I), rule["section"])
        for rule in _raw_section_rules
    ]
else:
    SECTION_RULES = [(re.compile(p, re.I), s) for p, s in _FALLBACK_SECTION_RULES]

# --- Nested-application markers ---------------------------------------------
# Some folders (typically a government/compliance folder) bundle real job
# applications inside a dated subfolder structure, e.g.
#   Applications/<Marker Folder>/<path_after_folder...>/<Month>/<Company>/...
# Each dated company folder should be tracked as its own real application,
# while everything else directly under the marker folder is grouped as one
# "compliance" item instead of being counted as a fake application. This is
# opt-in and disabled by default — see classify_config.json for the format
# and a disabled example. Only markers with "enabled": true are used.
NESTED_APPLICATION_MARKERS = [
    marker
    for marker in _CONFIG.get("nested_application_markers", [])
    if marker.get("enabled")
]


def slugify_section(name: str) -> str:
    """Turns an arbitrary top-level folder name into a stable section id,
    e.g. "Solar Panel Docs" -> "solar_panel_docs". This is what lets a
    user-created custom category (via "+ New Category" with a name that
    isn't one of the known presets/aliases above) become its own real
    Browse tab on the next rebuild, instead of being lumped into a single
    generic bucket. Conveniently, running a *known* section name (e.g.
    "Credentials", "Network", "Resume Library", "Leads", "Personal",
    "Misc") through this same function reproduces the exact section id
    those words already map to elsewhere (ui.py/frontend SECTION_LABELS),
    so the "+ New Category" preset buttons for those line up automatically
    without needing their own SECTION_RULES entries — only "Case
    Management" needed one, since its id ("compliance") isn't a slug of
    the label.
    """
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def classify_section(top_level_folder: str) -> str:
    for pattern, section in SECTION_RULES:
        if pattern.search(top_level_folder):
            return section
    return slugify_section(top_level_folder) or "misc"


# Files/dirs to ignore anywhere in the tree.
IGNORE_NAMES = {
    ".DS_Store", ".git", ".gitignore", "__pycache__", "_app",
    "node_modules", ".venv", "venv", "env",
}
IGNORE_SUFFIXES = {
    ".zip", ".synctex.gz", ".aux", ".log", ".out",
    ".tar", ".tar.gz", ".tgz", ".gz",
    # Disposable/derived database files — never real JobTracker content,
    # and doubly excluded (they also only ever live inside _app/, which is
    # skipped outright) so a stray copy elsewhere is never indexed either.
    ".db", ".db-journal", ".db-wal", ".db-shm", ".sqlite", ".sqlite3",
}


# --- Source-file classification --------------------------------------------
# Files that are editable/source artifacts rather than the generated
# document a company actually received. These are NEVER excluded from the
# index (they stay fully searchable/openable) — this only marks them so the
# UI can hide them from default document lists behind a toggle. See
# db.py/is_source and the frontend's "Show source files" control.
SOURCE_EXTENSIONS = {".tex"}


def is_source_file(filename: str) -> bool:
    return any(filename.lower().endswith(ext) for ext in SOURCE_EXTENSIONS)


def should_ignore(name: str) -> bool:
    """
    True if this single path component (a folder or file name) should be
    skipped while walking the JobTracker root. Covers four blanket rules
    on top of the explicit name list:
      - the app's own home, `_app/` (wherever it's nested), never indexed
      - any hidden file/dir (name starts with '.') — .git, .DS_Store,
        .venv, .jobtracker_root, etc. — without needing to enumerate
        every one
      - common dependency/venv directories (node_modules, venv, env) that
        sometimes get dropped next to project folders
      - archive/db files anywhere (.zip/.tar/.tar.gz backups, and stray
        .db/.sqlite files so a copied database never gets indexed as a
        "document")
    """
    if name in IGNORE_NAMES:
        return True
    if name.startswith("."):
        return True
    return any(name.lower().endswith(suf) for suf in IGNORE_SUFFIXES)


# --- Document type classification ------------------------------------------
RESUME_RE = re.compile(r"resume", re.I)
COVER_RE = re.compile(r"cover\s*-?letter|coverletter", re.I)
PREP_RE = re.compile(
    r"cheat\s*sheet|cheatsheet|interview\s*prep|prep\b|quiz|study|mock|troubleshoot",
    re.I,
)
REJECT_RE = re.compile(r"reject|not referred|eligible list not referred", re.I)
INTERVIEW_RE = re.compile(r"interview|phone screen|screener|schedule", re.I)
CONFIRM_RE = re.compile(
    r"thank you|application received|received by|confirmation|application status|"
    r"got it application|successful application|update",
    re.I,
)
POSTING_RE = re.compile(r"job bulletin|job description|job id|careers|job details", re.I)
CERT_RE = re.compile(r"coursera|certificat", re.I)
README_RE = re.compile(r"^readme", re.I)


def normalize_for_search(text: str) -> str:
    """
    Expand camelCase and normalize separators so filenames like
    'CheatSheet.pdf' or 'cover-letter.pdf' are tokenized as separate
    searchable words ('Cheat Sheet', 'cover letter') instead of one blob.
    """
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    text = re.sub(r"[_\-]+", " ", text)
    return text


def classify_doc_type(filename: str) -> str:
    if README_RE.match(filename):
        return "readme"
    if RESUME_RE.search(filename):
        return "resume"
    if COVER_RE.search(filename):
        return "cover_letter"
    if PREP_RE.search(filename):
        return "interview_prep"
    if REJECT_RE.search(filename):
        return "rejection_notice"
    if INTERVIEW_RE.search(filename):
        return "interview_notice"
    if CONFIRM_RE.search(filename):
        return "application_confirmation"
    if POSTING_RE.search(filename):
        return "job_posting"
    if CERT_RE.search(filename):
        return "certificate"
    return "other"


STATUS_PRIORITY = [
    # Checked in this order; first match wins. Order matters: an
    # interview_notice found alongside a rejection_notice should still show
    # as rejected (rejection is the more recent/authoritative signal).
    ("rejection_notice", "rejected"),
    ("interview_notice", "interviewing"),
    ("application_confirmation", "applied"),
    ("resume", "drafted"),
    ("cover_letter", "drafted"),
]


def infer_status(doc_types: set[str]) -> str:
    for doc_type, status in STATUS_PRIORITY:
        if doc_type in doc_types:
            return status
    return "unknown"


def normalize_company_key(name: str) -> str:
    """
    Loose key for suggesting possible duplicate companies (e.g. 'Bet365',
    'BET 365', 'Bet365 — ABET' all reduce to 'bet365'). Only used to power
    merge *suggestions* in the Manage view — never applied automatically,
    since a loose match can also be a false positive.
    """
    base = re.split(r"[—-]", name)[0]  # drop " — ABET" / " - via ..." suffixes
    return re.sub(r"[^a-z0-9]", "", base.lower())
