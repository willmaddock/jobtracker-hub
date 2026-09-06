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

Four providers have real multi-job block parsers, validated against real
fixture emails in tests/fixtures/email-source/ (CLAUDE_HANDOFF.md section
6): LinkedIn, Handshake, Lensa, and Indeed (Indeed dispatches to one of
two body parsers by subject shape -- see _parse_indeed()'s docstring). A
second, separate tier -- Layer 3b below -- covers senders where one email
is always exactly one job (Honeywell, McDonald's/jobs2web, AWS Educate,
Built In, Symplicity): a lightweight subject-line fallback rather than a
body-block parser, since there's no repeated structure to slice. That
tier is NOT yet validated against real fixture bodies -- see Layer 3b's
docstring.

Every other known job-alert domain (ZipRecruiter, Greenhouse, ...) is
recognized by detect_provider() but has no parser of either kind yet, and
extract_postings() correctly returns [] for it -- see the module
docstring in CLAUDE_HANDOFF.md section 10's closing note: "this is an
evolving provider list, not a reason to hard-code the whole product
around today's providers." Adding a new multi-job provider means adding
one `_parse_<provider>()` function and one branch in extract_postings();
adding a new single-job provider means adding a sender hint and a
provider id to _SINGLE_JOB_FALLBACK_PROVIDERS. The storage layer
(overrides_store.job_postings) and API layer (api.py's /api/job-postings)
don't change either way.
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
    ("lensa.com", "lensa"),               # real digest fixture validated -- see _parse_lensa
    # Single-job direct-notice senders (one email == one job, never a
    # multi-job digest) -- see _SINGLE_JOB_FALLBACK_PROVIDERS and Layer 3b
    # below. Added on user request from real inbox sender addresses;
    # unvalidated against real fixture bodies (no samples in
    # tests/fixtures/email-source/ yet -- CLAUDE_HANDOFF.md section 17).
    ("honeywell.com", "honeywell"),
    ("jobs2web.com", "jobs2web"),        # shared ATS, many employers (e.g. McDonald's)
    ("awseducate.com", "awseducate"),
    ("builtin.com", "builtin"),          # job-board/media site, not an employer
    ("symplicity.com", "symplicity"),    # career-services ATS (e.g. NSLS), not an employer
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
_SUPPORTED_PROVIDERS = {"linkedin", "handshake", "lensa", "indeed"}


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


# --- Layer 3: Lensa body structure --------------------------------------------
# Real fixture shape (tests/fixtures/email-source/lensa_digest_worky_and_5_
# more.pdf): each job is a run of "<Company>\n<Title>\n<Salary>" followed by
# a "<EmploymentType>\u2022<tag>\u2022<tag>..." meta line (the bullet is the
# reliable per-job terminator, same idea as Handshake's "\u2022"-joined meta
# line). One fixture job (Xcellent Technology Solutions) inserts a bare
# location line ("Denver, CO") between the salary and the meta line -- that
# case is handled by taking whatever extra buffered line exists as the real
# location, falling back to a "Remote" token inside the meta line otherwise.
# A meta line can itself wrap across two physical lines in the PDF extract
# when it ends on a bare "\u2022" (e.g. "...Remarkable Professional Growth\u2022"
# followed by "Good Salary & Benefits" on its own line) -- that continuation
# is stitched back on before splitting, or two of the fixture's real jobs
# would scramble into each other's neighbors. Terminated by "More jobs" /
# "GIG JOBS" (Amazon Flex, Survey Junkie, ...), which are Lensa's own
# continuation links and an unrelated gig-work section, never real digest
# jobs (CLAUDE_HANDOFF.md section 6).

_LENSA_STOP_MARKERS = re.compile(r"^more jobs|^gig jobs", re.IGNORECASE)

_LENSA_HEADER_NOISE = re.compile(
    r"^(from:|subject:|date:|to:|your job alerts for)", re.IGNORECASE,
)

_LENSA_SETTINGS_LINE = re.compile(r"edit settings\s*$", re.IGNORECASE)

_LENSA_META_RE = re.compile("\u2022")


def _parse_lensa(body: str) -> list[dict]:
    jobs: list[dict] = []
    buffer: list[str] = []
    pending_meta: str | None = None

    def flush(meta_line: str) -> None:
        buf = [b for b in buffer if b]
        if len(buf) < 3:
            # Not enough lines for a real Company/Title/Salary block --
            # never fabricate a job from a stray meta line.
            return
        company, title, salary = buf[0], buf[1], buf[2]
        location = buf[3] if len(buf) > 3 else None
        parts = [p.strip() for p in meta_line.split("\u2022")]
        employment_type = parts[0] if parts and parts[0] else None
        if location is None:
            for p in parts[1:]:
                if p.lower() == "remote":
                    location = p
                    break
        jobs.append({
            "title": title, "company": company, "location": location,
            "salary": salary, "employment_type": employment_type,
        })

    for line in _lines(body):
        if not line:
            continue
        if _LENSA_STOP_MARKERS.match(line):
            break
        if _LENSA_HEADER_NOISE.match(line) or _LENSA_SETTINGS_LINE.search(line):
            continue
        if pending_meta is not None:
            # Previous line was a wrapped meta line ending in "\u2022" --
            # this line is its continuation, not a new job's company.
            flush(pending_meta + line)
            buffer = []
            pending_meta = None
            continue
        if _LENSA_META_RE.search(line):
            if line.endswith("\u2022"):
                pending_meta = line
            else:
                flush(line)
                buffer = []
            continue
        buffer.append(line)

    return jobs


# --- Layer 3: Indeed body structure ---------------------------------------
# Real fixture shapes: a "digest" email (tests/fixtures/email-source/
# indeed_digest_hackerearth_and_18_more.pdf, subject "... and N more new
# jobs") and a "single-match" email (indeed_single_match_mytech_partners.pdf,
# subject "<Title> @ <Company>") -- dispatched by subject shape in
# extract_postings(), since the two bodies are laid out completely
# differently (see _INDEED_DIGEST_SUBJECT_RE below).
#
# The digest fixture's PDF-extracted text is genuinely scrambled by
# whatever screenshot-to-PDF process produced it: each job's Company/
# Location/Salary "card" prints in its own cluster, but that card's Title
# text prints somewhere else entirely -- grouped with the titles of
# *several other* cards from the same visual section, all appearing
# together right after that section's last card. The two clusters are
# each in the same left-to-right, top-to-bottom order as the real jobs,
# so extracting all 19 real Company/Location/Salary "cards" (via the one
# reliable structural cue: a Company line is always immediately followed
# by a Location-shaped line) and all remaining real Title lines (in
# document order) and pairing them up positionally recovers the correct
# 19 title/company/salary triples -- verified line-by-line against the
# fixture's source screenshot. Two known artifacts of that scrambling are
# filtered out before pairing so they don't shift the alignment: stray
# duplicate Salary/Location lines that land at page-break boundaries
# without a Company line in front of them, and a Company name that gets
# printed a second time (as an orphan line ahead of its own card) right
# before its title cluster.
_INDEED_KERNING_FIX_RE = re.compile(r"\b([YT])\s+(?=[a-z])")


def _fix_indeed_kerning(line: str) -> str:
    """The digest fixture's PDF extraction drops a stray space after a
    handful of capital letters ("Y our", "T eamcenter", "T echnical"),
    apparently a kerning/ligature artifact of whatever generated the PDF.
    Collapsing "<CAP> <lowercase...>" back together fixes it without
    touching any other text."""
    return _INDEED_KERNING_FIX_RE.sub(r"\1", line)


_INDEED_DIGEST_STOP_MARKERS = re.compile(r"^view more jobs", re.IGNORECASE)

_INDEED_HEADER_NOISE = re.compile(
    r"^(from:|subject:|date:|to:|find jobssign in)", re.IGNORECASE,
)

_INDEED_BADGE = re.compile(
    r"^(easily apply|responsive employer|fully remote)$", re.IGNORECASE,
)

_INDEED_SECTION_HEADER = re.compile(
    r"^(pays more, farther from you|flexible hours and schedule|"
    r"great bene.?ts|based on your previous jobs)$", re.IGNORECASE,
)

_INDEED_BLURB = re.compile(
    r"^your top pick$|^your background|could be a great match|"
    r"you.re interested in|apply now or explore", re.IGNORECASE,
)

# Broader than the module-level _SALARY_RE: Indeed's real fixtures use
# single-value forms with no range ("$56 an hour") as well as ranges, and
# "an hour"/"a year" rather than "/ yr"/"/ hr".
_INDEED_SALARY_RE = re.compile(
    r"\$[\d,]+(?:\.\d+)?\s*[Kk]?\s*(?:[-\u2013\u2014]|to)?\s*\$?[\d,]+(?:\.\d+)?\s*[Kk]?"
    r"\s*(?:an?\s*(?:hour|year)|/\s*(?:yr|year|hr|hour))",
    re.IGNORECASE,
)


def _looks_like_indeed_salary(line: str) -> bool:
    return bool(_INDEED_SALARY_RE.search(line)) and "$" in line


_INDEED_LOCATION_RE = re.compile(
    r"^(remote|united states|[\w .'\-]+\s*,\s*[A-Za-z]{2}(\s+\d{5})?)$",
    re.IGNORECASE,
)


def _parse_indeed_digest(body: str) -> list[dict]:
    raw = [_fix_indeed_kerning(ln) for ln in _lines(body)]
    lines: list[str] = []
    for ln in raw:
        if _INDEED_DIGEST_STOP_MARKERS.match(ln):
            break
        lines.append(ln)
    n = len(lines)

    def is_noise(ln: str) -> bool:
        return (
            not ln
            or _INDEED_HEADER_NOISE.match(ln)
            or _INDEED_BADGE.match(ln)
            or _INDEED_SECTION_HEADER.match(ln)
            or _INDEED_BLURB.match(ln)
        )

    # Pass 1: pull out every real Company/Location(/Salary) card via the
    # one reliable cue -- a Company line immediately followed by a
    # Location-shaped line.
    consumed = [False] * n
    cards: list[dict] = []
    i = 0
    while i < n:
        ln = lines[i]
        if is_noise(ln):
            i += 1
            continue
        if i + 1 < n and _INDEED_LOCATION_RE.match(lines[i + 1]):
            company, location = ln, lines[i + 1]
            j = i + 2
            salary = None
            if j < n and _looks_like_indeed_salary(lines[j]):
                salary = lines[j]
                j += 1
            for k in range(i, j):
                consumed[k] = True
            cards.append({"company": company, "location": location, "salary": salary})
            i = j
            continue
        i += 1

    # Pass 2: everything left over that isn't noise, a stray duplicate
    # Salary/Location artifact, or an orphaned repeat of a Company name
    # already captured in pass 1, is a real Title line, in the same
    # order as the cards above.
    company_names = {c["company"] for c in cards}
    titles: list[str] = []
    for idx, ln in enumerate(lines):
        if consumed[idx] or is_noise(ln):
            continue
        if _looks_like_indeed_salary(ln) or _INDEED_LOCATION_RE.match(ln):
            continue
        if ln in company_names:
            continue
        titles.append(ln)

    return [
        {
            "title": title, "company": card["company"], "location": card["location"],
            "salary": card["salary"], "employment_type": None,
        }
        for card, title in zip(cards, titles)
    ]


_INDEED_EMPLOYMENT_TYPE_RE = re.compile(
    r"^(full-time|part-time|contract|temporary|internship)$", re.IGNORECASE,
)


def _parse_indeed_single(subject: str | None, body: str) -> list[dict]:
    """Uses the subject's "<Title> @ <Company>" split (validated against
    the real Mytech Partners fixture) rather than the body -- the body is
    a fixed one-job layout, but the subject is the more reliable source
    for the title/company pair itself. Location/salary/employment_type
    are then pulled from the body, in whatever order they appear (the
    fixture has them as freestanding lines rather than a joined
    Handshake/Lensa-style meta line)."""
    if not subject or "@" not in subject:
        return []
    title, _, company = subject.partition("@")
    title, company = title.strip(), company.strip()
    if not title or not company:
        return []
    location = salary = employment_type = None
    for ln in _lines(body):
        if not ln:
            continue
        if location is None and _INDEED_LOCATION_RE.match(ln):
            location = ln
            continue
        if salary is None and _looks_like_indeed_salary(ln):
            salary = ln
            continue
        if employment_type is None and _INDEED_EMPLOYMENT_TYPE_RE.match(ln):
            employment_type = ln
            continue
        if location and salary and employment_type:
            break
    return [{
        "title": title, "company": company, "location": location,
        "salary": salary, "employment_type": employment_type,
    }]


_INDEED_DIGEST_SUBJECT_RE = re.compile(r"and \d+ more", re.IGNORECASE)


def _parse_indeed(subject: str | None, body: str) -> list[dict]:
    """Dispatches Indeed mail by subject shape -- see the module note
    above for why the digest and single-match bodies each need their own
    parser rather than one shared one. A subject that matches neither
    shape yields [] rather than a guess (CLAUDE_HANDOFF.md section 11)."""
    if subject and _INDEED_DIGEST_SUBJECT_RE.search(subject):
        return _parse_indeed_digest(body)
    return _parse_indeed_single(subject, body)


# --- Layer 3b: single-job direct-notice fallback -----------------------------
# For senders where one email is always exactly one job -- a corporate
# ATS/careers-notification sender (Honeywell, McDonald's-via-jobs2web, AWS
# Educate) or a job-board single-listing alert (Built In, Symplicity) --
# rather than a multi-job digest like LinkedIn/Handshake/Lensa/Indeed. There is no
# repeated block structure to slice here (Layer 3 above), so instead of a
# body parser this reads the one signal that's reliably present: the
# subject line, which these notifications almost always phrase as
# "<Title> at <Company>" (e.g. "Software Engineer at Honeywell").
#
# UNVALIDATED against real fixture bodies -- no sample emails from these
# senders exist yet in tests/fixtures/email-source/ (CLAUDE_HANDOFF.md
# section 17 calls for testing against real fixtures before this can be
# trusted the way LinkedIn/Handshake are). Added on explicit user request
# ahead of that validation; the user should sanity-check real results and
# report back any garbled title/company so the pattern below can be fixed
# against real evidence instead of another guess.
_SINGLE_JOB_FALLBACK_PROVIDERS = {
    "honeywell", "jobs2web", "awseducate", "builtin", "symplicity",
}

# Providers whose sender domain IS the employer, so a subject line that
# doesn't parse cleanly can still fall back to a real company name.
# Deliberately excludes jobs2web (shared multi-tenant ATS -- the domain is
# the ATS vendor, not the employer, same reasoning as mail_app_store.py's
# _GENERIC_SENDER_DOMAINS) and builtin/symplicity (job-board/ATS
# platforms relaying someone else's listing, not employers themselves).
_KNOWN_EMPLOYER_COMPANY_NAMES = {
    "honeywell": "Honeywell",
    "awseducate": "AWS Educate",
}

_SUBJECT_TITLE_AT_COMPANY = re.compile(
    r"^(.*?)\s+at\s+([A-Z][\w&'.,\- ]{1,60}?)\s*[!.]?\s*$", re.IGNORECASE,
)


def _split_subject_title_company(subject: str | None) -> tuple[str | None, str | None]:
    """Best-effort ("<Title> at <Company>", "Title") split of a single-job
    notification subject. Returns (None, None) if nothing usable -- never
    fabricates a title out of thin air."""
    if not subject:
        return None, None
    m = _SUBJECT_TITLE_AT_COMPANY.match(subject.strip())
    if m:
        title = m.group(1).strip(" -\u2013:")
        company = m.group(2).strip(" -\u2013.,")
        if title and company:
            return title, company
    return subject.strip() or None, None


def _parse_single_job_fallback(provider: str, subject: str | None) -> list[dict]:
    title, company = _split_subject_title_company(subject)
    if not title:
        # No subject at all -- nothing to safely build a posting from.
        return []
    if not company:
        company = _KNOWN_EMPLOYER_COMPANY_NAMES.get(provider)
    return [{
        "title": title, "company": company, "location": None,
        "salary": None, "employment_type": None,
    }]


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
    if provider in _SUPPORTED_PROVIDERS:
        if provider == "linkedin":
            raw_jobs = _parse_linkedin(body)
        elif provider == "handshake":
            raw_jobs = _parse_handshake(body)
        elif provider == "lensa":
            raw_jobs = _parse_lensa(body)
        elif provider == "indeed":
            raw_jobs = _parse_indeed(subject, body)
        else:  # pragma: no cover - guarded by _SUPPORTED_PROVIDERS above
            raw_jobs = []
    elif provider in _SINGLE_JOB_FALLBACK_PROVIDERS:
        raw_jobs = _parse_single_job_fallback(provider, subject)
    else:
        return []

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
