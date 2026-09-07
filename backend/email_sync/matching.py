"""
Provider-independent email classification/matching logic, ported from
_app/mail_app_store.py.

_app/mail_app_store.py mixed two very different kinds of code together:
AppleScript-against-Mail.app plumbing (list_mail_app_accounts,
search_messages, get_message_source, ...) that only exists because the
original app was macOS/Mail.app-only, and plain-Python classification
logic (term matching, ATS/digest phrase heuristics, posting-URL
extraction, company-name guessing) that has nothing to do with
AppleScript at all -- it just happened to live in the same file because
it was only ever *called* from AppleScript-driven code.

Per docs/DJANGO_MIGRATION_PLAN.md, the accounts/sync/discoveries
cluster's actual OAuth-provider design is Phase 9's own rewrite, not a
port -- there is no Gmail/Outlook client here yet. This module only
ports the second kind of code: the pure classification/matching
functions that will be needed unchanged no matter which provider ends
up fetching the messages, since "does this message look like an ATS
notification" or "does this URL look like a job posting" doesn't care
whether the message came from an AppleScript `whose` clause or a
Gmail API list call. Byte-for-byte logic where the original was pure
Python; only names losing their leading underscore where they're now
this module's own public API instead of a same-file private helper.

NOT ported here (left for the actual sync-provider slice):
  - list_mail_app_accounts, _run_applescript, _resolve_mailbox_script,
    _escape_applescript_string -- AppleScript/Mail.app only.
  - search_messages, search_unmatched_messages, get_message_source,
    get_message_preview, get_posting_urls_for_message -- each builds
    an AppleScript query or drives one; the *classification* pieces
    they lean on (term matching, ATS/digest heuristics, posting-URL
    extraction) are what's ported below, so a future OAuth-provider
    version of those functions can import this module instead of
    reimplementing the heuristics.
"""
from __future__ import annotations

import html as _html
import re
from email import message_from_string
from email.parser import HeaderParser

from documents.extraction import extract_urls

# --- Message-ID / thread helpers --------------------------------------------

_MESSAGE_ID_RE = re.compile(r"<[^<>\s]+>")


def extract_thread_message_ids(raw_headers: str) -> set[str]:
    """Parse a raw RFC 5322 header block and return every Message-ID
    this message's In-Reply-To/References headers point at (its own
    Message-ID is NOT included -- callers add that separately once a
    hit is confirmed). Uses email.parser.HeaderParser rather than a
    regex over the raw block directly, since HeaderParser correctly
    un-folds continuation lines (a References header on a long thread
    routinely wraps across several physical lines) before we scan for
    Message-ID tokens. Malformed/empty header blocks just yield no
    tokens rather than raising."""
    if not raw_headers or not raw_headers.strip():
        return set()
    try:
        parsed = HeaderParser().parsestr(raw_headers)
    except Exception:
        return set()
    ids: set[str] = set()
    for header_name in ("In-Reply-To", "References"):
        for value in parsed.get_all(header_name, []):
            ids.update(_MESSAGE_ID_RE.findall(value))
    return ids


# --- Term matching -----------------------------------------------------------
#
# A term (a company name or role label pulled from a tracked item) is only
# safe to match on its own once it's both long enough and not one of a
# stoplist of common short acronyms/placeholders -- filtering noisy matches
# up front rather than trying to clean them up after the fact.
#
# That length/stoplist check alone is NOT sufficient, though: a term that's
# long enough and not on the stoplist -- a role label of "Tech", say -- can
# still substring-match the middle of an unrelated word ("Technical",
# "Biotech"). That gap is closed separately by term_matches_wholeword()
# below, applied to whatever candidate messages a provider's own coarse
# search already narrowed down to.
MIN_MATCH_TERM_LENGTH = 4
_GENERIC_MATCH_TERMS = {
    "it", "hr", "pm", "qa", "ai", "ml", "ux", "ui", "bi", "vp", "dev",
    "eng", "job", "jobs", "root", "misc", "n/a", "na", "tbd", "temp",
}


def is_usable_match_term(term: str | None) -> bool:
    """True if `term` is specific enough to safely drive a coarse
    substring search on its own. Filters both very short strings and a
    stoplist of common job-title acronyms/placeholders that are short
    but still generic once stripped of surrounding punctuation, e.g.
    the "(root)" role label used for items with no role subfolder."""
    if not term:
        return False
    cleaned = term.strip().strip("()").strip().lower()
    if not cleaned or cleaned in _GENERIC_MATCH_TERMS:
        return False
    return len(cleaned) >= MIN_MATCH_TERM_LENGTH


def term_matches_wholeword(term: str, *texts: str | None) -> bool:
    """True if `term` appears in any of `texts` as a whole word (or
    whole word-sequence, for a multi-word term like "Metro Water
    Recovery"), not merely as a substring.

    This exists because a coarse mailbox search (Mail.app's `contains`,
    or an equivalent provider-side text search) is typically a plain
    case-insensitive substring test with no word-boundary awareness.
    is_usable_match_term() above filters terms that are short or
    explicitly generic (e.g. "IT"), but that doesn't help a term like a
    role label of "Tech": four characters, not on the stoplist,
    perfectly reasonable as a role name on its own -- and yet a
    substring test on "Tech" also matches "Technical", "high-tech",
    "Biotech", etc., silently attaching unrelated companies' mail to
    whatever application happens to have "Tech" as its role. (This is
    exactly what surfaced against a real tracker: a "Metro Water
    Recovery / Tech" item picking up "Technical Project Manager at
    Ladders", "... at StrataBlue", and other listings that have nothing
    to do with Metro Water Recovery.)

    Rather than another stoplist entry -- which only ever covers the
    specific words someone happened to notice -- this re-checks each
    coarse-search hit with a word-boundary-anchored regex before it's
    trusted, catching every case of this shape at once. The coarse
    search is still meant to run first to narrow down the candidate
    set (whatever that looks like for a given provider); this is a
    precision filter applied afterward, in Python, on the already-small
    matched set it returns."""
    pattern = r"(?<![A-Za-z0-9])" + re.escape(term.strip()) + r"(?![A-Za-z0-9])"
    compiled = re.compile(pattern, re.IGNORECASE)
    return any(text and compiled.search(text) for text in texts)


# --- ATS / digest sender & subject heuristics --------------------------------
#
# Used to spot "this looks like application-related mail" among a mailbox's
# other traffic -- for surfacing candidates the user hasn't logged as a
# tracked application yet. Deliberately biased toward precision over
# recall: a missed real application is recoverable (it'll still show up
# once the user manually logs it and a sync re-scans), but a discovery
# queue full of newsletter/marketing noise trains the user to stop
# checking it. Both lists are intentionally ordinary English/common ATS
# vendor names, not exact-match rules -- callers should still treat these
# as case-insensitive substring tests.
ATS_SUBJECT_PHRASES = [
    "thank you for applying",
    "thanks for applying",
    "application received",
    "application has been received",
    "we received your application",
    "your application to",
    "your application for",
    "application to",
    "application submitted",
    "next steps in your application",
    "interview",
    "phone screen",
    "schedule a call",
    "moving forward with your application",
]

# Domains that ONLY ever send transactional, employer-triggered mail --
# an application confirmation, an interview invite, an ATS status update.
# Matching on sender alone is safe here: these vendors don't also blast
# job-alert digests or marketing from the same address.
ATS_ONLY_SENDER_DOMAINS = [
    "myworkday.com",
    "icims.com",
    "greenhouse.io",
    "lever.co",
    "smartrecruiters.com",
    "taleo.net",
    "successfactors.com",
    "jobvite.com",
    "ashbyhq.com",
    "bamboohr.com",
    "brassring.com",
]

# Domains that send BOTH real application-related mail AND high-volume
# job-alert digests / recruiter marketing / "people you may know" mail to
# the same address -- e.g. "LinkedIn Job Alerts <jobalerts-noreply@
# linkedin.com>" sending "New jobs in Denver Metropolitan Area match your
# preferences" with a company name buried in one of several unrelated
# listings. For these, sender alone is NOT enough signal: the subject
# must also contain one of ATS_SUBJECT_PHRASES, same bar as any other
# unrecognized sender.
MIXED_SIGNAL_SENDER_DOMAINS = [
    "indeedemail.com",
    "linkedin.com",
    "ziprecruiter.com",
]

ATS_SENDER_DOMAINS = ATS_ONLY_SENDER_DOMAINS + MIXED_SIGNAL_SENDER_DOMAINS

# Subject phrasing distinctive of a bulk job-alert/recommendation digest
# rather than a message about one specific application -- excludes a
# candidate even if it otherwise matched an ATS phrase or sender domain.
# These digests are recurring, multi-listing, and never something the
# user "applied to" -- they're the single biggest source of false
# positives in a discovery queue in practice.
DIGEST_SUBJECT_PHRASES = [
    "job alert",
    "jobs match your preferences",
    "new jobs in",
    "new jobs for you",
    "recommended jobs",
    "jobs for you",
    "jobs you may be interested in",
    "jobs matching",
    "your job recommendations",
    "people you may know",
    "your weekly job",
]

# Common ATS no-reply sender domains carry no employer-name signal at all
# (e.g. "no-reply@myworkday.com" is Workday's own domain, not the
# employer running that Workday instance) -- guess_company_from_email()
# skips these rather than surfacing "Myworkday" as a fake company name.
GENERIC_SENDER_DOMAINS = set(ATS_SENDER_DOMAINS) | {
    "gmail.com", "outlook.com", "hotmail.com", "icloud.com", "yahoo.com",
}


def sender_domain(sender: str | None) -> str | None:
    """Pulls the lowercased domain out of a raw sender field, e.g.
    "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>" ->
    "linkedin.com". Returns None if no @domain is found."""
    if not sender:
        return None
    m = re.search(r"@([\w.-]+)", sender)
    return m.group(1).lower() if m else None


def is_ats_subject_phrase(subject: str | None) -> bool:
    """True if `subject` contains any ATS_SUBJECT_PHRASES entry
    (case-insensitive substring)."""
    if not subject:
        return False
    low = subject.lower()
    return any(phrase in low for phrase in ATS_SUBJECT_PHRASES)


def is_digest_subject(subject: str | None) -> bool:
    """True if `subject` reads as a bulk job-alert/recommendation digest
    -- see DIGEST_SUBJECT_PHRASES."""
    if not subject:
        return False
    low = subject.lower()
    return any(phrase in low for phrase in DIGEST_SUBJECT_PHRASES)


def looks_like_untracked_application(
    subject: str | None,
    sender: str | None,
    always_posting_senders: set[str] | None = None,
) -> tuple[bool, bool]:
    """Provider-agnostic version of the `whose`-condition
    search_unmatched_messages() used to build for AppleScript: does
    this message look like application-related mail worth surfacing in
    the discovery queue, before checking whether it already matches a
    tracked item's own terms (that part is caller-specific -- see
    term_matches_wholeword()).

    Returns (is_candidate, force_posting):
      - is_candidate: True if the subject/sender combination looks
        application-related and isn't excluded as a bulk digest.
      - force_posting: True if a whitelisted sender (see
        `always_posting_senders`, e.g. JobPostingSender rows) is what
        made this a candidate -- callers should classify these
        kind="posting" unconditionally, bypassing
        is_job_posting_style_subject(), same as the original
        AppleScript version's dedicated whitelist branch.

    `always_posting_senders` entries are matched as a substring of the
    raw `sender` field, not exact equality -- see JobPostingSender's
    docstring for why (Mail.app has no reliable way to know a sender's
    exact display-name formatting up front)."""
    clean_posting_senders = {
        s.strip() for s in (always_posting_senders or set()) if s and s.strip()
    }
    force_posting = bool(sender and any(s in sender for s in clean_posting_senders))
    if force_posting:
        return True, True

    domain = sender_domain(sender)
    ats_subject = is_ats_subject_phrase(subject)
    sender_is_ats_only = bool(domain) and any(
        d in domain for d in ATS_ONLY_SENDER_DOMAINS
    )
    sender_is_mixed_signal = bool(domain) and any(
        d in domain for d in MIXED_SIGNAL_SENDER_DOMAINS
    )

    positive = ats_subject or sender_is_ats_only or (sender_is_mixed_signal and ats_subject)
    if not positive:
        return False, False
    if is_digest_subject(subject):
        return False, False
    return True, False


# --- Job-posting-style subject / URL heuristics ------------------------------
#
# Subject phrasing distinctive of a single job-alert/listing notice --
# "KPMG just posted a 78% match Front End Engineer...", "Just in: Comcast
# has new Junior Developer jobs open" -- as opposed to DIGEST_SUBJECT_
# PHRASES above, which is bulk multi-listing digest mail. These slip past
# the digest exclusion because they're framed around ONE company/listing
# (often the same company as an existing tracked item), so they'd
# otherwise land in the ambiguous-application queue purely on
# company-name overlap even though the user never applied to the specific
# posting mentioned. Regexes, not plain substrings, since the
# company/role name sits between fixed phrasing on both sides.
_JOB_POSTING_SUBJECT_PATTERNS = [
    r"just posted a \d+% match",
    r"new .* jobs open",
    r"just in:.*has new",
]


def is_job_posting_style_subject(subject: str | None) -> bool:
    """True if `subject` reads as a job-alert/listing notice about a
    specific posting rather than confirmation of an application the
    user made -- see _JOB_POSTING_SUBJECT_PATTERNS. Used to route mail
    to a discovery's kind="posting" (never the ambiguous-application
    queue) regardless of whether its company name happens to overlap an
    existing tracked item."""
    if not subject:
        return False
    return any(re.search(p, subject, re.IGNORECASE) for p in _JOB_POSTING_SUBJECT_PATTERNS)


# Domains that plausibly point at an actual job posting/listing page, as
# opposed to a tracking pixel, unsubscribe link, employer logo image, or
# the ATS's own marketing site. Not exhaustive -- this only needs to catch
# the common cases well enough to be worth showing; anything that misses
# just means the card shows no link, never a wrong one.
_JOB_POSTING_URL_DOMAINS = [
    "linkedin.com/jobs", "indeed.com", "greenhouse.io", "lever.co",
    "myworkdayjobs.com", "icims.com", "smartrecruiters.com", "taleo.net",
    "jobvite.com", "ashbyhq.com", "bamboohr.com", "ziprecruiter.com",
    "workable.com", "breezy.hr", "recruiting.com", "jobs.",
]

# Path fragments that mean a URL is almost never the posting itself, even
# if its domain matched above (e.g. a Greenhouse "unsubscribe" link is
# still on greenhouse.io). Checked case-insensitively against the whole
# URL, not just the domain.
#
# "utm_" is deliberately NOT in this list -- LinkedIn (and most ATSs)
# attach utm_*/trk= tracking params to their REAL per-job listing links
# in every alert email, so filtering on utm_ would exclude essentially
# every genuine posting link a digest could ever contain, not just
# tracking pixels/unsubscribe links. Tracking parameters don't stop a URL
# from opening the right job page, so they're not a reason to reject it.
_NON_POSTING_URL_HINTS = [
    "unsubscribe", "optout", "opt-out", "preferences", "privacy",
    "terms-of-service", "/track",
]

# Path fragments that mean a URL points at a job-board's generic
# collection/search/"view all" landing page rather than one specific
# listing. These are filtered out before any URL-to-job positional count
# comparison, so a digest's one "view all N jobs" header link doesn't
# inflate the URL count and silently zero out every job's link via a
# count-mismatch safety net.
_GENERIC_COLLECTION_URL_HINTS = [
    "/jobs/search", "/jobs/collections", "/jobs?", "/jobs/view-all",
    "see-all-jobs", "viewalljobs", "/alerts/", "/digest/",
]


def extract_posting_urls(body: str | None) -> list[str]:
    """Every URL in a job-alert email's body that plausibly points at a
    distinct posting/listing, in body order (de-duped, order preserved
    -- see documents.extraction.extract_urls()), for digest emails that
    bundle several listings into one message (e.g. a LinkedIn Job Alerts
    digest with several separate job cards). Never authoritative -- an
    empty list just means the card shows no links, same "no fake link"
    rule as guess_posting_url()."""
    if not body:
        return []
    out = []
    for url in extract_urls(body):
        low = url.lower()
        if any(hint in low for hint in _NON_POSTING_URL_HINTS):
            continue
        if any(hint in low for hint in _GENERIC_COLLECTION_URL_HINTS):
            continue
        if any(domain in low for domain in _JOB_POSTING_URL_DOMAINS):
            out.append(url)
    return out


# Domains that are almost never the job itself even when they show up as
# a prominent link in a corporate notification email -- social/footer
# chrome, not a posting. Kept separate from _NON_POSTING_URL_HINTS (path
# fragments) since these are whole domains.
_NON_POSTING_LINK_DOMAINS = [
    "facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com",
    "linkedin.com/company", "linkedin.com/school", "apps.apple.com",
    "play.google.com", "mailto:",
]


def extract_primary_cta_url(body: str | None) -> str | None:
    """Best-effort single "Apply Now"/call-to-action link for a one-job
    corporate notification email, where extract_posting_urls()'s curated
    ATS-domain whitelist (_JOB_POSTING_URL_DOMAINS) often misses entirely
    since a single employer's own careers site or in-house ATS domain
    isn't something that can be enumerated in advance.

    Deliberately looser than extract_posting_urls(): does not require
    the domain to match a known job board, only that it isn't
    unsubscribe/preference/tracking chrome (_NON_POSTING_URL_HINTS) or an
    obvious social/footer link (_NON_POSTING_LINK_DOMAINS). That's only
    an acceptable trade because this is meant to be called for messages
    already known (from the sender) to be a single job notice -- there's
    no risk of picking the wrong job out of several, only "some link" vs.
    "no link". Still returns None rather than a wrong guess when nothing
    remains -- same "no fake link" rule as guess_posting_url()."""
    if not body:
        return None
    for url in extract_urls(body):
        low = url.lower()
        if any(hint in low for hint in _NON_POSTING_URL_HINTS):
            continue
        if any(hint in low for hint in _GENERIC_COLLECTION_URL_HINTS):
            continue
        if any(domain in low for domain in _NON_POSTING_LINK_DOMAINS):
            continue
        return url
    return None


def guess_posting_url(body: str | None) -> str | None:
    """Best-effort pick of the one URL in a job-alert email's body that
    actually points at the posting/listing. Never authoritative --
    returns None rather than guessing when nothing in the body looks
    right, since a wrong link is worse than no link. Picks the first URL
    (in body order, which is usually the order the email's own CTA
    buttons appear) whose domain matches a known job board/ATS and whose
    path doesn't look like an unsubscribe/tracking link. Delegates to
    extract_posting_urls() so single-link callers don't need their own
    logic; new code that wants every listing in a digest should call
    extract_posting_urls() directly."""
    urls = extract_posting_urls(body)
    return urls[0] if urls else None


def normalize_linkedin_comm_url(url: str) -> str:
    """LinkedIn's email links route through a "/comm/" redirector
    wrapped in a huge per-recipient tracking query string (midToken,
    otpToken, lipi, trk, eid, ...) that shouldn't be persisted. For a
    linkedin.com URL, drops the query string entirely and collapses the
    "/comm/" segment, e.g.
    "https://www.linkedin.com/comm/jobs/view/123?trk=..." becomes
    "https://www.linkedin.com/jobs/view/123" -- which also happens to be
    what makes the link match _JOB_POSTING_URL_DOMAINS's "linkedin.com/
    jobs" entry at all. Non-LinkedIn URLs are returned unchanged -- there's
    no evidence other ATSs need the same cleanup, and some (e.g. a
    query-param-only listing id) would break if their query string were
    stripped."""
    if "linkedin.com" not in url.lower():
        return url
    return url.split("?", 1)[0].replace("/comm/", "/", 1)


# Matches an href attribute's value inside decoded HTML markup. Applied to
# text already run through email.message.Message.get_payload(decode=True),
# which handles Content-Transfer-Encoding (quoted-printable/base64) --
# so by the time this regex runs, "=3D" has already become "=" and this
# is looking at ordinary (if messy, real-world) HTML.
_HREF_RE = re.compile(r'href\s*=\s*"([^"]*)"', re.IGNORECASE)


def extract_html_source_urls(raw_source: str | None) -> list[str]:
    """Every plausible job-posting URL recoverable from a message's raw
    MIME source -- needed because extract_posting_urls() operates on a
    mail client's own plain-text rendering of a message, and for an HTML
    email that rendering keeps visible link text ("View job") but throws
    away the underlying <a href="..."> URL entirely. This instead parses
    the actual MIME structure, decodes each text/html part's
    Content-Transfer-Encoding (quoted-printable/base64, via Python's
    email library rather than hand-rolled decoding), pulls every
    href="..." value out of the decoded markup, HTML-unescapes it
    (&amp; -> &), and runs it through the same domain/exclusion filters
    as extract_posting_urls() (plus LinkedIn's "/comm/" + tracking-query
    cleanup -- see normalize_linkedin_comm_url()).

    Returns [] (never raises) for a None/empty source, a source that
    isn't parseable as a MIME message, or one with no text/html part --
    "no links recoverable this way" is a normal, expected outcome (a
    plain-text-only email, for instance), not an error; callers should
    fall back to extract_posting_urls() on the plain-text body in that
    case."""
    if not raw_source:
        return []
    try:
        msg = message_from_string(raw_source)
    except Exception:
        return []

    html_parts = list(msg.walk()) if msg.is_multipart() else [msg]

    hrefs: list[str] = []
    seen_hrefs = set()
    for part in html_parts:
        try:
            if part.get_content_type() != "text/html":
                continue
            payload = part.get_payload(decode=True)
        except Exception:
            continue
        if not payload:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            text = payload.decode("utf-8", errors="replace")
        for m in _HREF_RE.finditer(text):
            href = _html.unescape(m.group(1))
            if href and href not in seen_hrefs:
                seen_hrefs.add(href)
                hrefs.append(href)

    out = []
    for href in hrefs:
        normalized = normalize_linkedin_comm_url(href)
        low = normalized.lower()
        if any(hint in low for hint in _NON_POSTING_URL_HINTS):
            continue
        if any(hint in low for hint in _GENERIC_COLLECTION_URL_HINTS):
            continue
        if any(domain in low for domain in _JOB_POSTING_URL_DOMAINS):
            out.append(normalized)
    return out


def guess_company_from_email(subject: str | None, sender: str | None) -> str | None:
    """Best-effort employer-name guess for the discovery review queue --
    never authoritative, always shown to the user as an editable field
    before anything is created. Tries a couple of common subject
    phrasings first ("Your application to Acme", "Thank you for applying
    to Acme") since the subject is usually written by (or templated for)
    the actual employer; falls back to the sender's domain, skipping
    known ATS/webmail domains that would only produce a fake "company"
    name like "Myworkday" or "Gmail"."""
    if subject:
        for pattern in (
            r"application (?:to|for|at)\s+([A-Z][\w&' .-]{1,40}?)(?:[!.,]|\s*[-\u2013]\s*|\s+has\b|\s+is\b|$)",
            r"thank(?:s| you) for applying to\s+([A-Z][\w&' .-]{1,40}?)(?:[!.,]|$)",
            r"your interview (?:with|at)\s+([A-Z][\w&' .-]{1,40}?)(?:[!.,]|$)",
        ):
            m = re.search(pattern, subject, re.IGNORECASE)
            if m:
                guess = m.group(1).strip(" -\u2013.,")
                if guess:
                    return guess

    domain = sender_domain(sender)
    if domain and domain not in GENERIC_SENDER_DOMAINS:
        label = domain.split(".")[0]
        if label:
            return label.replace("-", " ").title()

    return None
