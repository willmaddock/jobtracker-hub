"""
Deterministic job-posting extraction for JobTracker's Email Sync redesign.

See CLAUDE_HANDOFF.md sections 1-11 for the full design rationale. In
one line: a job-alert/digest email (LinkedIn, Handshake, ...) can
describe *several* distinct jobs in one message body, and this module's
job is to turn that body into a list of individual job-posting records
-- never a single "one email = one posting" record, and never an LLM
call (see CLAUDE_HANDOFF.md section 11: "Do not make an LLM the primary
deterministic parser unless the user explicitly approves that
architecture" -- not yet approved).

Layered design (CLAUDE_HANDOFF.md section 10):
  Layer 1 -- source recognition:   detect_provider()
  Layer 2 -- subject signals:      is_digest_subject() (advisory only)
  Layer 3 -- body structure:       _parse_linkedin() / _parse_handshake()
  Layer 4 -- URL evidence:         reuses mail_app_store.extract_posting_urls

Only two providers have real per-provider block parsers so far: LinkedIn
and Handshake -- the two sources with real fixture emails in
tests/fixtures/email-source/ (CLAUDE_HANDOFF.md section 6). Every other
known job-alert domain (Indeed, ZipRecruiter, Greenhouse, ...) is
recognized by detect_provider() but has no body parser yet and
extract_postings() correctly returns [] for it -- see the module
docstring in CLAUDE_HANDOFF.md section 10's closing note: "this is an
evolving provider list, not a reason to hard-code the whole product
around today's providers." Adding a new provider means adding one
`_parse_<provider>()` function and one branch in extract_postings(); the
storage layer (overrides_store.job_postings) and API layer
(api.py's /api/job-postings) don't change.
"""

from __future__ import annotations

import hashlib
import re

# --- Layer 1: source recognition --------------------------------------------

# Sender-domain fragments that identify a known job-alert/listing source.
# Matched against the raw `sender` string (e.g.
# "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>"), case-insensitive
# substring match -- deliberately loose the same way mail_app_store's own
# sender-domain lists are (see its _ATS_SENDER_DOMAINS docstring).
_PROVIDER_SENDER_HINTS: list[tuple[str, str]] = [
    ("linkedin.com", "linkedin"),
    ("joinhandshake.com", "handshake"),
    ("indeed.com", "indeed"),
    ("ziprecruiter.com", "ziprecruiter"),
]


def detect_provider(sender: str | None) -> str | None:
    """Best-effort provider id from the message sender, or None if this
    isn't a sender we recognize at all. A recognized provider with no
    body parser yet (see module docstring) still returns its id here --
    extract_postings() is what decides whether that id has real parsing
    support, keeping "we know who this is from" and "we know how to
    parse it" as two separate, separately-testable questions."""
    if not sender:
        return None
    low = sender.lower()
    for hint, provider in _PROVIDER_SENDER_HINTS:
        if hint in low:
            return provider
    return None


# Providers with an actual body-structure parser implemented below.
_SUPPORTED_PROVIDERS = {"linkedin", "handshake"}


# --- Layer 2: subject signals (advisory only, per CLAUDE_HANDOFF.md 7.4/7.6) --

_DIGEST_SUBJECT_HINTS = re.compile(
    r"job alert|jobs match|new jobs|jobs for you|jobs you may|"
    r"job recommendations|weekly job|jobs round-?up|sees you as a top applicant",
    re.IGNORECASE,
)


def is_digest_subject(subject: str | None) -> bool:
    """Advisory only -- CLAUDE_HANDOFF.md section 7.2/7.4 is explicit that
    a legitimate job digest does NOT necessarily say "job alert" in its
    subject (the real LinkedIn fixture's subject is just "Software
    Engineer at Haystack"). Callers should treat this as one signal among
    several (sender + body structure), never a hard requirement -- see
    extract_postings(), which does not gate on this at all and instead
    lets the body parser itself decide (an email with no parseable
    job-shaped blocks naturally yields zero postings regardless of
    subject wording)."""
    return bool(subject and _DIGEST_SUBJECT_HINTS.search(subject))


# --- shared line-level helpers ------------------------------------------------

def _lines(body: str) -> list[str]:
    return [ln.strip() for ln in body.splitlines()]


_SALARY_RE = re.compile(
    r"\$[\d,]+(?:\.\d+)?\s*[Kk]?\s*(?:[-\u2013\u2014]|to)\s*\$?[\d,]+(?:\.\d+)?\s*[Kk]?"
    r"\s*(?:/\s*(?:yr|year|hr|hour))?",
)


def _looks_like_salary(line: str) -> bool:
    return bool(_SALARY_RE.search(line)) and "$" in line


# --- Layer 3: LinkedIn body structure ----------------------------------------
# Real fixture shape (tests/fixtures/email-source/linkedin_job_alert_
# haystack.pdf), one block per job, in this order:
#   <Title>
#   <Company> \u00b7 <Location>
#   ["Actively recruiting"]           (status line, no job of its own)
#   ["$<low>-<high> / year"]          (salary, attaches to the job just above)
# Terminated by a "See all jobs" link, after which everything is
# navigation/footer chrome, never a job (CLAUDE_HANDOFF.md section 6).

_LINKEDIN_STOP_MARKERS = re.compile(
    r"^(see all jobs|stand out and let hirers|try premium|"
    r"install linkedin widgets|stay updated at a glance|add widget|"
    r"this email was intended for|you are receiving job alert|"
    r"manage job alerts|\u00a9\s*\d{4}\s*linkedin)",
    re.IGNORECASE,
)

_LINKEDIN_HEADER_NOISE = re.compile(
    r"^(from:|subject:|date:|to:|your job aler|new jobs in .* match your preferences)",
    re.IGNORECASE,
)

_LINKEDIN_STATUS_LINE = re.compile(r"^actively recruiting$", re.IGNORECASE)


def _parse_linkedin(body: str) -> list[dict]:
    jobs: list[dict] = []
    current: dict | None = None

    for line in _lines(body):
        if not line:
            continue
        if _LINKEDIN_STOP_MARKERS.match(line):
            break
        if _LINKEDIN_HEADER_NOISE.match(line):
            continue
        if _LINKEDIN_STATUS_LINE.match(line):
            continue
        if current and _looks_like_salary(line):
            current["salary"] = line
            continue
        if current and current.get("company") is None and "\u00b7" in line:
            company, _, location = line.partition("\u00b7")
            current["company"] = company.strip() or None
            current["location"] = location.strip() or None
            continue
        # Anything else is a new job title.
        if current:
            jobs.append(current)
        current = {"title": line, "company": None, "location": None,
                   "salary": None, "employment_type": None}

    if current:
        jobs.append(current)

    # A job whose title line was actually a stray body line (never got a
    # company) is dropped -- see CLAUDE_HANDOFF.md section 11: "return
    # zero for ordinary application emails" / don't fabricate a job with
    # no real evidence behind it.
    return [j for j in jobs if j.get("company")]


# --- Layer 3: Handshake body structure ---------------------------------------
# Real fixture shape (tests/fixtures/email-source/handshake_weekly_jobs_
# roundup.pdf): each job is closed by its own "<salary> \u2022 <employment
# type> \u2022 <location>" meta line; everything buffered since the previous
# job's meta line is that job's Company + Title lines (title may wrap
# across more than one line -- see the "Unified Communications..." fixture
# job). Terminated by "View more jobs", which is a continuation action,
# never a job itself (CLAUDE_HANDOFF.md section 6).

_HANDSHAKE_STOP_MARKERS = re.compile(
    r"^(view more jobs|update your career interests|manage email preferences|"
    r"unsubscribe)",
    re.IGNORECASE,
)

_HANDSHAKE_HEADER_NOISE = re.compile(
    r"^(from:|subject:|date:|to:|new jobs just for you)", re.IGNORECASE,
)


def _normalize_spaced_out(line: str) -> str:
    """Collapses letter-spaced header text ("Y o u r  w e e k l y") to
    normal spacing so it matches header-noise detection. Only applied to
    the header-noise check, never to real job data."""
    return re.sub(r"\s+", " ", line).strip()


def _is_handshake_header_banner(line: str) -> bool:
    collapsed = re.sub(r"(?<=\w)\s(?=\w)", "", _normalize_spaced_out(line)).lower()
    return "yourweeklyjobsround" in collapsed or "roundup" in collapsed


_HANDSHAKE_META_RE = re.compile(r"\u2022")


def _parse_handshake(body: str) -> list[dict]:
    jobs: list[dict] = []
    buffer: list[str] = []

    def flush_job(meta_line: str) -> None:
        parts = [p.strip() for p in meta_line.split("\u2022")]
        salary = parts[0] if len(parts) > 0 and parts[0] else None
        employment_type = parts[1] if len(parts) > 1 and parts[1] else None
        location = parts[2] if len(parts) > 2 and parts[2] else None

        buf = [b for b in buffer if b]
        if not buf:
            return
        if len(buf) == 1:
            company, title = None, buf[0]
        else:
            company, title = buf[0], " ".join(buf[1:])
        jobs.append({
            "title": title, "company": company, "location": location,
            "salary": salary, "employment_type": employment_type,
        })

    for line in _lines(body):
        if not line:
            continue
        if _HANDSHAKE_STOP_MARKERS.match(line):
            break
        if _HANDSHAKE_HEADER_NOISE.match(line) or _is_handshake_header_banner(line):
            continue
        if _HANDSHAKE_META_RE.search(line):
            flush_job(line)
            buffer = []
            continue
        buffer.append(line)

    return jobs


# --- entry point --------------------------------------------------------------

def extract_postings(sender: str | None, subject: str | None, body: str | None) -> list[dict]:
    """The one function callers (api.py) need. Returns a list of raw job
    dicts (title/company/location/salary/employment_type -- posting_url
    is attached separately by the caller via mail_app_store.
    extract_posting_urls(), since URL-to-job association isn't reliable
    enough yet to do positionally here -- see CLAUDE_HANDOFF.md section
    10's Layer 4 note). Always returns [] rather than raising: an empty
    or unparseable body, or a provider with no parser yet, is a normal
    "nothing extractable" case, not an error (CLAUDE_HANDOFF.md section
    11)."""
    if not body:
        return []
    provider = detect_provider(sender)
    if provider not in _SUPPORTED_PROVIDERS:
        return []
    if provider == "linkedin":
        raw_jobs = _parse_linkedin(body)
    elif provider == "handshake":
        raw_jobs = _parse_handshake(body)
    else:  # pragma: no cover - guarded by _SUPPORTED_PROVIDERS above
        raw_jobs = []

    for j in raw_jobs:
        j["source"] = provider
    return raw_jobs


# --- deduplication (CLAUDE_HANDOFF.md section 9) -----------------------------

def normalize_title(title: str | None) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def normalize_company(company: str | None) -> str:
    return re.sub(r"\s+", " ", (company or "").strip().lower())


def normalize_url(url: str | None) -> str:
    """Strips a trailing query string / fragment so tracking-parameter
    variants of the same link (utm_source=..., etc.) collapse to one
    identity, and drops a trailing slash so .../jobs/123 and
    .../jobs/123/ match."""
    if not url:
        return ""
    u = url.split("#", 1)[0].split("?", 1)[0].strip().rstrip("/")
    return u.lower()


def compute_dedupe_key(
    account_id: str,
    message_id: str,
    posting_url: str | None,
    title: str | None,
    company: str | None,
) -> str:
    """account_id + normalized posting URL when a URL is available
    (CLAUDE_HANDOFF.md section 9's preferred identity); otherwise
    account_id + message_id + normalized title + normalized company. A
    linkless job is intentionally scoped to *this* message_id rather than
    made global -- section 9 only asks that the SAME email scanned twice
    not duplicate, not that two different emails mentioning a
    similarly-titled job collapse into one, which risks over-collapsing
    genuinely different jobs (section 9's fourth acceptance case)."""
    norm_url = normalize_url(posting_url)
    if norm_url:
        raw = f"url::{account_id}::{norm_url}"
    else:
        raw = (
            f"msg::{account_id}::{message_id}::"
            f"{normalize_title(title)}::{normalize_company(company)}"
        )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
