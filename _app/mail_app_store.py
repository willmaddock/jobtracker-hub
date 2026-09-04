"""
Connected-email-account handshake: AppleScript against Mail.app.

This app targets macOS only, so this module replaces the old
accounts_store.py OAuth/IMAP scaffold entirely -- there is no Google
Cloud Console app to register, no Azure AD app, no client_id/secret,
no IMAP username/password, and no keychain token storage. Every
account this module can see is one already configured by the user in
System Settings -> Internet Accounts with "Mail" enabled. Mail.app
itself owns the login, the OAuth refresh, and the sync; this module
just asks Mail.app questions over AppleScript (via the `osascript`
CLI) and never touches a credential of any kind.

The very first call in a fresh install pops the standard macOS
"'JobTracker Hub' wants to control 'Mail'" Automation permission
prompt (also manageable at System Settings -> Privacy & Security ->
Automation). If the user has previously denied that prompt, every
call below raises MailAppError with a message telling them exactly
where to go fix it -- see _run_applescript().

STATUS: list_mail_app_accounts() and search_messages() run real
AppleScript and are usable as-is. sync wiring (api.py's
/api/accounts/{id}/sync) drives search_messages() per open
application item -- see that route's docstring for the matching
logic.
"""

from __future__ import annotations

import html as _html
import re
import subprocess
import uuid
from email import message_from_string
from email.parser import HeaderParser

import extract

# Matches an href attribute's value inside decoded HTML markup. Applied to
# text already run through email.message.Message.get_payload(decode=True),
# which handles Content-Transfer-Encoding (quoted-printable/base64) for us
# -- so by the time this regex runs, "=3D" has already become "=" and this
# is looking at ordinary (if messy, real-world) HTML. See
# extract_html_source_urls().
_HREF_RE = re.compile(r'href\s*=\s*"([^"]*)"', re.IGNORECASE)

# Hit records are joined with the ASCII Record Separator (0x1E) instead of
# "\n" -- unlike the other fields, a message's raw headers legitimately
# contain their own embedded newlines (RFC 5322 header folding), which
# would otherwise be indistinguishable from a hit boundary.
_HIT_SEPARATOR = "\x1e"

_MESSAGE_ID_RE = re.compile(r"<[^<>\s]+>")


def _extract_thread_message_ids(raw_headers: str) -> set[str]:
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

# Mail.app's AppleScript dictionary represents the RFC822 Message-ID
# header as the "message id" property of a message -- stable across
# re-syncs and re-launches, unlike its numeric "id" (a per-session
# index Mail.app reassigns), so that's what we key account_matches on.
_LIST_ACCOUNTS_SCRIPT = """
tell application "Mail"
    set out to {}
    repeat with acct in every account
        set acctName to name of acct
        set acctEmail to acctName
        try
            set addrs to email addresses of acct
            if (count of addrs) > 0 then set acctEmail to item 1 of addrs
        end try
        set end of out to acctName & "|||" & acctEmail
    end repeat
    set AppleScript's text item delimiters to "\\n"
    set outStr to out as text
    set AppleScript's text item delimiters to ""
    return outStr
end tell
"""


class MailAppError(RuntimeError):
    """Raised when osascript is missing, times out, or Mail.app itself
    errors for any reason other than a denied Automation permission
    (see MailAppPermissionError below for that specific case). Callers
    (api.py) turn the message straight into an HTTP error body -- it's
    already written for a human, not a stack trace."""


class MailAppPermissionError(MailAppError):
    """Specifically a denied Automation permission -- as opposed to a
    timeout, a missing mailbox/account, or any other MailAppError.
    Callers use this distinction to decide whether an account should
    be flagged 'blocked' (permission problem, needs the user to go fix
    a macOS setting) versus just surfacing the error for one failed
    attempt (everything else, where retrying might just work)."""


class MailAppNoInboxError(MailAppError):
    """Mail.app has the account, but no mailbox we can identify as its
    Inbox is available yet -- e.g. an account added moments ago that
    Mail.app hasn't finished populating. Distinct from MailAppError so
    a future caller could tell the user to open Mail.app and let the
    account finish loading, rather than a generic failure message.
    Currently surfaces through the same generic-failure path as any
    other MailAppError in api.py's sync route (not 'blocked', since
    retrying -- after Mail.app has had time to sync -- should work)."""


def _run_applescript(script: str, timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise MailAppError(
            "osascript isn't available -- connected accounts only work on macOS."
        )
    except subprocess.TimeoutExpired:
        raise MailAppError(
            "Mail.app didn't respond in time. Make sure it isn't stuck on a "
            "dialog (e.g. an iCloud/Exchange password prompt) and try again."
        )

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        lowered = stderr.lower()
        if "not allowed" in lowered or "-1743" in stderr or "not authorized" in lowered:
            raise MailAppPermissionError(
                "JobTracker Hub isn't allowed to control Mail yet. Open System "
                "Settings \u2192 Privacy & Security \u2192 Automation, enable "
                "\u201cMail\u201d for JobTracker Hub, then try again."
            )
        if "jobtracker_no_inbox" in lowered:
            raise MailAppNoInboxError(
                "Mail.app hasn't loaded a mailbox for this account yet. Open "
                "Mail.app, click this account in the sidebar, give it a minute "
                "to finish loading its messages, then try syncing again."
            )
        raise MailAppError(stderr or "osascript failed with no error output.")

    return result.stdout.strip()


def list_mail_app_accounts() -> list[dict]:
    """Every account currently configured in Mail.app, regardless of
    whether JobTracker Hub has already connected it -- api.py's
    /api/accounts/mail-app/available route filters out the ones
    already present in the `accounts` table. Returns
    [{"name": <Mail.app account name>, "email": <address>}, ...].
    `name` is what search_messages() needs; `email` is only for
    display."""
    raw = _run_applescript(_LIST_ACCOUNTS_SCRIPT)
    if not raw:
        return []

    accounts = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or "|||" not in line:
            continue
        name, email = line.split("|||", 1)
        accounts.append({"name": name.strip(), "email": email.strip()})
    return accounts


def _escape_applescript_string(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _resolve_mailbox_script(mailbox: str) -> str:
    """Shared AppleScript snippet that resolves `acct`'s mailbox named
    `mailbox` into the `targetBox` variable, or raises the
    JOBTRACKER_NO_INBOX marker if it can't find one. Used by both
    search_messages() and search_unmatched_messages() so there's exactly
    one place encoding the two-step resolve-then-fallback-scan strategy
    documented in search_messages()'s docstring (point 2) -- duplicating
    this logic risks one copy getting the real-Mac fix and the other not.
    """
    escaped_mailbox = _escape_applescript_string(mailbox)
    if mailbox == "INBOX":
        return """
        set targetBox to missing value
        try
            set targetBox to inbox of acct
        end try
        if targetBox is missing value then
            repeat with mb in (every mailbox of acct)
                if name of mb is "INBOX" then
                    set targetBox to mb
                    exit repeat
                end if
            end repeat
        end if
        if targetBox is missing value then
            error "JOBTRACKER_NO_INBOX: no Inbox mailbox found for this account yet"
        end if
        """
    return f"""
        set targetBox to missing value
        try
            set targetBox to mailbox "{escaped_mailbox}" of acct
        end try
        if targetBox is missing value then
            repeat with mb in (every mailbox of acct)
                if name of mb is "{escaped_mailbox}" then
                    set targetBox to mb
                    exit repeat
                end if
            end repeat
        end if
        if targetBox is missing value then
            error "JOBTRACKER_NO_INBOX: no mailbox named \\"{escaped_mailbox}\\" found for this account yet"
        end if
        """


# A term this short/generic will substring-match huge swaths of unrelated
# text through Mail.app's `contains` operator -- e.g. a role label of "IT"
# matches "wa-IT-ing", "oppor-tu-n-IT-y", "ident-IT-y", "recru-IT-ing", and
# so on, in any subject or sender across the whole mailbox. Confirmed in
# practice: a real 110-application tracker had a two-letter "IT" role label
# pull in 18 unrelated matches (Apple, Honeywell, MongoDB, random LinkedIn
# job digests...) for one application alone. sync_account() and
# discover_new_applications() both run every company/role term through
# is_usable_match_term() before it reaches an AppleScript `contains` clause,
# rather than trying to filter noisy results after the fact.
#
# This length/stoplist check alone is NOT sufficient, though: a term that's
# long enough and not on the stoplist -- a role label of "Tech", say -- can
# still substring-match the middle of an unrelated word ("Technical",
# "Biotech"). That gap is closed separately, in Python, on the hits Mail.app
# actually returns -- see _term_matches_wholeword() below, used by both
# search_messages() and search_unmatched_messages().
MIN_MATCH_TERM_LENGTH = 4
_GENERIC_MATCH_TERMS = {
    "it", "hr", "pm", "qa", "ai", "ml", "ux", "ui", "bi", "vp", "dev",
    "eng", "job", "jobs", "root", "misc", "n/a", "na", "tbd", "temp",
}


def is_usable_match_term(term: str | None) -> bool:
    """True if `term` is specific enough to safely drive an AppleScript
    `contains` search on its own (see the module-level note above for why
    this exists). Filters both very short strings and a stoplist of common
    job-title acronyms/placeholders that are short but still generic once
    stripped of surrounding punctuation, e.g. the "(root)" role label
    load_applications() uses for items with no role subfolder."""
    if not term:
        return False
    cleaned = term.strip().strip("()").strip().lower()
    if not cleaned or cleaned in _GENERIC_MATCH_TERMS:
        return False
    return len(cleaned) >= MIN_MATCH_TERM_LENGTH


def _term_matches_wholeword(term: str, *texts: str | None) -> bool:
    """True if `term` appears in any of `texts` as a whole word (or
    whole word-sequence, for a multi-word term like "Metro Water
    Recovery"), not merely as a substring.

    This exists because Mail.app's `contains` operator -- the only
    string test its AppleScript dictionary offers, used to build the
    coarse `whose` filter in search_messages()/search_unmatched_
    messages() below -- is a plain case-insensitive substring test with
    no word-boundary awareness. is_usable_match_term() above filters
    terms that are short or explicitly generic (e.g. "IT"), but that
    doesn't help a term like a role label of "Tech": four characters,
    not on the stoplist, perfectly reasonable as a role name on its
    own -- and yet `contains "Tech"` also matches "Technical", "high-
    tech", "Biotech", etc., silently attaching unrelated companies'
    mail to whatever application happens to have "Tech" as its role.
    (This is exactly what surfaced against a real tracker: a "Metro
    Water Recovery / Tech" item picking up "Technical Project Manager
    at Ladders", "... at StrataBlue", and other listings that have
    nothing to do with Metro Water Recovery.)

    Rather than another stoplist entry -- which only ever covers the
    specific words someone happened to notice -- this re-checks each
    AppleScript hit in Python with a word-boundary-anchored regex
    before it's trusted, catching every case of this shape at once.
    Mail.app's `contains` clause is still used first to do the actual
    scan (see search_messages()'s docstring, point 1, for why: it's
    the only way that doesn't time out against a real several-hundred-
    message inbox); this is a precision filter applied afterward, in
    Python, on the already-small matched set it returns."""
    pattern = r"(?<![A-Za-z0-9])" + re.escape(term.strip()) + r"(?![A-Za-z0-9])"
    compiled = re.compile(pattern, re.IGNORECASE)
    return any(text and compiled.search(text) for text in texts)


def search_messages(
    account_name: str,
    terms: list[str],
    mailbox: str = "INBOX",
    limit: int = 15,
    role_terms: list[str] | None = None,
    thread_ids: list[str] | None = None,
) -> list[dict]:
    """Search one Mail.app account's mailbox for messages whose subject
    or sender contains any of `terms` (case-insensitive substring, e.g.
    a company name and/or role title pulled from an application item).
    Returns [{"message_id": str, "subject": str, "sender": str,
    "received_at": iso-ish str, "matched_via": "text"|"thread",
    "thread_message_ids": [str, ...]}, ...] capped at `limit`, in
    whatever order Mail.app's own mailbox storage returns them (not
    guaranteed most-recent-first).

    `thread_ids` (optional): a set of Message-IDs already confirmed to
    belong to this item (see overrides_store.thread_identifiers). Any
    message whose In-Reply-To/References headers cite one of these is
    trusted as a match deterministically ("matched_via": "thread"),
    bypassing the whole-word/role-confirmation heuristics entirely --
    those exist to disambiguate ordinary English words appearing in a
    subject line, which doesn't apply to an opaque Message-ID token. A
    reply that shares no company/role text at all (e.g. "Re: your
    submission") still attaches correctly this way. Every returned hit
    -- text-matched or thread-matched -- also reports its own
    `thread_message_ids` (its Message-ID plus whatever its own
    In-Reply-To/References cite), so a thread can keep growing from
    either a later reply or an earlier one picked up on a future sync.

    `role_terms` (optional) marks which entries in `terms` are role
    labels rather than company names -- e.g. for an item with company
    "Metro Water Recovery" and role "Tech", pass
    terms=["Metro Water Recovery", "Tech"], role_terms=["Tech"]. When
    given, a hit is only trusted if a *non-role* term (the company)
    matched, or there was no company term available to check against
    in the first place. This closes a gap the word-boundary check
    alone doesn't: a role label can be a perfectly ordinary, unrelated
    whole word -- confirmed against a real tracker, where a "Home
    Depot / Resume" item's role term "Resume" whole-word-matched
    "Your resume was received by Claritev" (nothing to do with Home
    Depot), and a "Metro Water Recovery / Tech" item's role term
    "Tech" whole-word-matched "Project Manager (Non Tech) at ...
    (WMATA)" (nothing to do with Metro Water Recovery either). Neither
    is a substring-inside-a-word false positive -- both are genuine
    whole-word hits on a common single-word role label with no company
    confirmation, which is why _term_matches_wholeword() alone can't
    catch them; this requires the company identity to actually show up
    too. Omit `role_terms` (or pass all of `terms` as company terms) to
    keep the old any-term-matches behavior, e.g. for
    search_unmatched_messages()'s exclusion use, where being generous
    about what counts as "already tracked" is the safer direction.

    Three things below exist because real-Mac testing against a live
    718-item, 110-application tracker surfaced them, not because they
    were anticipated up front:

    1. `messages of targetBox whose <condition>` filters inside Mail.app
       as one Apple Event, instead of the tempting "repeat with msg in
       (messages of targetBox)" pattern, which fetches and tests every
       message one Apple Event at a time and reliably times out against
       a real inbox of any size (confirmed: it hung past 60s on a ~700-
       message Gmail account here).  Only the (small) matched set gets
       iterated to pull out properties.
    2. Neither a single property nor a single literal name reliably
       resolves an account's Inbox. `mailbox "INBOX" of acct` raised a
       real -1728 "Can't get object" error against a live Gmail
       account; switching to the built-in `inbox of acct` property
       *looked* like the fix (it's documented as the per-account
       equivalent) but raised the exact same -1728 against that same
       account and a second, unrelated Hotmail account once tested for
       real -- so `inbox of acct` isn't reliably backed by an actual
       mailbox object either, at least not immediately after an
       account is connected. The account's mailbox list (`every
       mailbox of acct`) is small (a handful of top-level folders), so
       resolving the target box below tries the built-in property
       first, swallows a failure with `try`, and falls back to
       scanning that list by name -- two independent ways to find the
       same mailbox instead of betting on either one alone.
    3. If neither approach finds anything, that's a real, different
       situation from "syntax found the wrong object" -- most likely
       Mail.app hasn't finished loading that account's mailboxes yet.
       This raises a distinct "JOBTRACKER_NO_INBOX" marker (parsed by
       _run_applescript into MailAppNoInboxError) instead of a bare
       AppleScript error code, so the failure message tells the user
       what to actually do (open Mail.app, let the account load)."""
    clean_terms = [t.strip() for t in (terms or []) if t and t.strip()]
    clean_thread_ids = {t.strip() for t in (thread_ids or []) if t and t.strip()}
    if not clean_terms and not clean_thread_ids:
        return []
    clean_role_terms = {t.strip() for t in (role_terms or []) if t and t.strip()}
    clean_company_terms = [t for t in clean_terms if t not in clean_role_terms]
    resolve_box = _resolve_mailbox_script(mailbox)

    if clean_terms:
        escaped_terms = [_escape_applescript_string(t) for t in clean_terms]
        condition = " or ".join(f'(subject contains "{t}" or sender contains "{t}")' for t in escaped_terms)
    else:
        # No usable text terms at all (e.g. an item whose only known
        # identity so far is a thread id from a prior sync) -- still
        # worth scanning the mailbox, since Mail.app's own condition
        # can't filter on headers, so fall back to matching everything
        # and let the Python-side thread-id check below do the work.
        condition = "true"

    script = f"""
    tell application "Mail"
        set acct to account "{_escape_applescript_string(account_name)}"
        {resolve_box}
        set matchedMsgs to (messages of targetBox whose {condition})
        set hits to {{}}
        set n to 0
        repeat with msg in matchedMsgs
            set msgId to "unknown"
            try
                set msgId to message id of msg
            end try
            set msgSubject to ""
            try
                set msgSubject to subject of msg
            end try
            set msgSender to ""
            try
                set msgSender to sender of msg
            end try
            set msgDate to ""
            try
                set msgDate to (date received of msg) as string
            end try
            set msgHeaders to ""
            try
                set msgHeaders to all headers of msg
            end try
            set end of hits to msgId & "|||" & msgSubject & "|||" & msgSender & "|||" & msgDate & "|||" & msgHeaders
            set n to n + 1
            if n \u2265 {int(limit)} then exit repeat
        end repeat
        set AppleScript's text item delimiters to "{_HIT_SEPARATOR}"
        set hitsStr to hits as text
        set AppleScript's text item delimiters to ""
        return hitsStr
    end tell
    """
    raw = _run_applescript(script, timeout=60)
    if not raw:
        return []

    results = []
    for record in raw.split(_HIT_SEPARATOR):
        record = record.strip()
        if not record:
            continue
        parts = record.split("|||", 4)
        if len(parts) != 5:
            continue
        message_id, subject, sender, received_at, raw_headers = parts
        message_id = message_id.strip()
        subject = subject.strip()
        sender = sender.strip()
        this_message_ids = _extract_thread_message_ids(raw_headers)
        if message_id and message_id != "unknown":
            this_message_ids.add(message_id)

        # A thread id already confirmed for this item -- via In-Reply-To
        # or References citing a Message-ID we've matched before -- is
        # trusted deterministically, skipping the text heuristics below
        # entirely. See this function's docstring for why: an opaque
        # Message-ID token has no ambiguous-English-word problem the
        # way a subject-line company/role term does.
        matched_via_thread = bool(clean_thread_ids & this_message_ids)

        if matched_via_thread:
            matched_via = "thread"
        elif clean_terms:
            # Mail.app's `contains` (used to build the whose-clause
            # above) is a plain substring test, so a hit here isn't
            # necessarily a real match -- re-check in Python that at
            # least one term actually appears as a whole word, not
            # just a substring (e.g. a "Tech" role term shouldn't
            # count a hit on "Technical Project Manager"). See
            # _term_matches_wholeword()'s docstring for the real-world
            # case this fixes.
            matched_terms = [t for t in clean_terms if _term_matches_wholeword(t, subject, sender)]
            if not matched_terms:
                continue
            # A role-only whole-word hit isn't enough on its own when
            # there was a company term available to confirm identity
            # against -- see this function's docstring for the
            # "Resume"/"Tech" cases that motivated this. If every term
            # that actually matched is a role term, and we had a
            # company term in play that just didn't match, reject the
            # hit.
            if clean_company_terms and not any(t not in clean_role_terms for t in matched_terms):
                continue
            matched_via = "text"
            # A hit is "company-only" when a company term is in play but
            # nothing role-specific actually matched -- either because no
            # usable role term was ever passed in (e.g. a role label of
            # "IT", dropped upstream by is_usable_match_term()), or a role
            # term was passed but simply didn't appear in this message.
            # Callers use this to tell "we know it's this company, but
            # nothing here confirms it's *this* company's specific open
            # role" apart from "we're confident which role this is about"
            # -- see api.py's sync_account() docstring for why that
            # distinction matters when a company has more than one open
            # item at once (the exact shape of the Adams County / Public
            # Health Department bug this was written for: a generic
            # agency-wide rejection notice whole-word-matches "Adams
            # County" with nothing in the subject/sender to say *which*
            # Adams County application it's actually about).
            company_only = bool(clean_company_terms) and not any(t in clean_role_terms for t in matched_terms)
        else:
            # No text terms were given at all, and this message's
            # headers don't cite a known thread id either -- nothing
            # to confirm identity with.
            continue

        results.append({
            "message_id": message_id or f"{account_name}:{subject}:{received_at}",
            "subject": subject or None,
            "sender": sender or None,
            "received_at": received_at.strip() or None,
            "matched_via": matched_via,
            "thread_message_ids": sorted(this_message_ids),
            # False for a thread match (deterministic -- an opaque
            # Message-ID reference has no "which sibling role" ambiguity)
            # and for any hit where a role term itself matched.
            "company_only": False if matched_via == "thread" else company_only,
        })
    return results


# Heuristics for "this looks like application-related mail" -- used only
# by search_unmatched_messages() below, never by search_messages() (which
# already knows exactly what it's looking for via a tracked item's own
# company/role terms). Deliberately biased toward precision over recall:
# a missed real application is recoverable (it'll still show up once you
# manually log it and sync), but a queue full of newsletter/marketing
# noise trains the user to stop checking it. Both lists are intentionally
# ordinary English/common ATS vendor names, not exact match rules --
# Mail.app's `contains` is a case-insensitive substring test.
_ATS_SUBJECT_PHRASES = [
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
# you job-alert digests or marketing from the same address.
_ATS_ONLY_SENDER_DOMAINS = [
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
# must also contain one of _ATS_SUBJECT_PHRASES, same bar as any other
# unrecognized sender. Confirmed against a real inbox where this was
# previously flooding the discovery queue with digest mail (see
# _DIGEST_SUBJECT_PHRASES below for the second half of that fix).
_MIXED_SIGNAL_SENDER_DOMAINS = [
    "indeedemail.com",
    "linkedin.com",
    "ziprecruiter.com",
]

_ATS_SENDER_DOMAINS = _ATS_ONLY_SENDER_DOMAINS + _MIXED_SIGNAL_SENDER_DOMAINS

# Subject phrasing distinctive of a bulk job-alert/recommendation digest
# rather than a message about one specific application -- excludes a
# candidate even if it otherwise matched an ATS phrase or sender domain.
# These digests are recurring, multi-listing, and never something the
# user "applied to" -- they're the single biggest source of false
# positives in the discovery queue in practice.
_DIGEST_SUBJECT_PHRASES = [
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
_GENERIC_SENDER_DOMAINS = set(_ATS_SENDER_DOMAINS) | {
    "gmail.com", "outlook.com", "hotmail.com", "icloud.com", "yahoo.com",
}


# Subject phrasing distinctive of a single job-alert/listing notice --
# "KPMG just posted a 78% match Front End Engineer...", "Just in: Comcast
# has new Junior Developer jobs open" -- as opposed to _DIGEST_SUBJECT_
# PHRASES above, which is bulk multi-listing digest mail. These slip past
# the digest exclusion because they're framed around ONE company/listing
# (often the same company as an existing tracked item), so they used to
# land in the ambiguous-application queue purely on company-name overlap
# even though the user never applied to the specific posting mentioned.
# Regexes, not plain substrings, since the company/role name sits between
# fixed phrasing on both sides (see is_job_posting_style_subject()).
_JOB_POSTING_SUBJECT_PATTERNS = [
    r"just posted a \d+% match",
    r"new .* jobs open",
    r"just in:.*has new",
]


def is_job_posting_style_subject(subject: str | None) -> bool:
    """True if `subject` reads as a job-alert/listing notice about a
    specific posting rather than confirmation of an application the user
    made -- see _JOB_POSTING_SUBJECT_PATTERNS. Used to route mail to
    discovered_matches.kind='posting' (never the ambiguous-application
    queue) regardless of whether its company name happens to overlap an
    existing tracked item -- see overrides_store.add_discovered_match's
    `kind` docstring and api.py's sync_account()/discover_new_applications()."""
    import re

    if not subject:
        return False
    return any(re.search(p, subject, re.IGNORECASE) for p in _JOB_POSTING_SUBJECT_PATTERNS)


# Domains that plausibly point at an actual job posting/listing page, as
# opposed to a tracking pixel, unsubscribe link, employer logo image, or
# the ATS's own marketing site. Not exhaustive -- this only needs to catch
# the common cases well enough to be worth showing; anything that misses
# just means the card shows no link, never a wrong one (see
# guess_posting_url()'s docstring).
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
# AUDIT_FINDINGS.md Finding 4: "utm_" used to be in this list. That's
# wrong -- LinkedIn (and most ATSs) attach utm_*/trk= tracking params to
# their REAL per-job listing links in every alert email, so that entry
# was excluding essentially every genuine posting link a digest could
# ever contain, not just tracking pixels/unsubscribe links. Confirmed
# against the real testing DB: 100% of stored job_postings had
# posting_url = NULL. Tracking parameters don't stop a URL from opening
# the right job page, so they're not a reason to reject it.
_NON_POSTING_URL_HINTS = [
    "unsubscribe", "optout", "opt-out", "preferences", "privacy",
    "terms-of-service", "/track",
]

# Path fragments that mean a URL points at a job-board's generic
# collection/search/"view all" landing page rather than one specific
# listing (AUDIT_FINDINGS.md Finding 4). These are filtered out before
# the URL-to-job positional count comparison in
# api.py's _extract_and_store_job_postings, so a digest's one "view all
# N jobs" header link no longer inflates the URL count and silently
# zeroes out every job's link via the count-mismatch safety net (see
# tests/test_audit_findings.py's Finding 3 fix, which that safety net
# still preserves for genuine mismatches).
_GENERIC_COLLECTION_URL_HINTS = [
    "/jobs/search", "/jobs/collections", "/jobs?", "/jobs/view-all",
    "see-all-jobs", "viewalljobs", "/alerts/", "/digest/",
]


def extract_posting_urls(body: str | None) -> list[str]:
    """Every URL in a job-alert email's body that plausibly points at a
    distinct posting/listing, in body order (de-duped, order preserved --
    see extract.extract_urls()), for digest emails that bundle several
    listings into one message (see discoveries-sender-classification-and-
    digests-spec.md Part 5.5b -- e.g. a LinkedIn Job Alerts digest with
    six separate job cards). Same domain/exclusion lists as
    guess_posting_url() (which now delegates to this), but collects every
    matching URL instead of returning on the first hit. Never
    authoritative -- an empty list just means the card shows no links,
    same "no fake link" rule as guess_posting_url()."""
    if not body:
        return []
    out = []
    for url in extract.extract_urls(body):
        low = url.lower()
        if any(hint in low for hint in _NON_POSTING_URL_HINTS):
            continue
        if any(hint in low for hint in _GENERIC_COLLECTION_URL_HINTS):
            continue
        if any(domain in low for domain in _JOB_POSTING_URL_DOMAINS):
            out.append(url)
    return out


def guess_posting_url(body: str | None) -> str | None:
    """Best-effort pick of the one URL in a job-alert email's body that
    actually points at the posting/listing, for display on the Job
    Postings board card (see docs/specs/discoveries-board-v2-spec.md Part 5).
    Never authoritative -- returns None rather than guessing when nothing
    in the body looks right, since a wrong link is worse than no link.
    Picks the first URL (in body order, which is usually the order the
    email's own CTA buttons appear) whose domain matches a known job
    board/ATS and whose path doesn't look like an unsubscribe/tracking
    link. Kept for backward compat -- delegates to extract_posting_urls()
    so single-link callers/tests don't need to change; new code that
    wants every listing in a digest should call extract_posting_urls()
    directly."""
    urls = extract_posting_urls(body)
    return urls[0] if urls else None


def _normalize_linkedin_comm_url(url: str) -> str:
    """LinkedIn's email links route through a "/comm/" redirector wrapped
    in a huge per-recipient tracking query string (midToken, otpToken,
    lipi, trk, eid, ...) that we don't want persisted to job_postings.
    posting_url. For a linkedin.com URL, drops the query string entirely
    and collapses the "/comm/" segment, e.g.
    "https://www.linkedin.com/comm/jobs/view/123?trk=..." becomes
    "https://www.linkedin.com/jobs/view/123" -- which also happens to be
    what makes the link match _JOB_POSTING_URL_DOMAINS's "linkedin.com/jobs"
    entry at all (see AUDIT_FINDINGS.md's later "/comm/" note). Non-LinkedIn
    URLs are returned unchanged -- this app has no evidence other ATSs need
    the same cleanup, and some (e.g. a query-param-only listing id) would
    break if their query string were stripped."""
    if "linkedin.com" not in url.lower():
        return url
    return url.split("?", 1)[0].replace("/comm/", "/", 1)


def extract_html_source_urls(raw_source: str | None) -> list[str]:
    """Every plausible job-posting URL recoverable from a message's raw
    MIME source (see get_message_source()) -- the fix for the deeper bug
    behind AUDIT_FINDINGS.md Finding 4: even after that finding's utm_
    filter fix, extract_posting_urls() operates on Mail.app's own
    plain-text rendering of a message (`content of msg`), and for an
    HTML email that rendering keeps visible link text ("View job") but
    throws away the underlying <a href="..."> URL entirely -- there was
    nothing for the utm_ filter (or any body-text filter) to act on in
    the first place for a real HTML digest. This function instead parses
    the actual MIME structure, decodes each text/html part's
    Content-Transfer-Encoding (quoted-printable/base64, via Python's
    email library rather than hand-rolled decoding), pulls every
    href="..." value out of the decoded markup, HTML-unescapes it
    (&amp; -> &), and runs it through the same domain/exclusion filters
    as extract_posting_urls() (plus LinkedIn's "/comm/" + tracking-query
    cleanup -- see _normalize_linkedin_comm_url()).

    Returns [] (never raises) for a None/empty source, a source that
    isn't parseable as a MIME message, or one with no text/html part --
    "no links recoverable this way" is a normal, expected outcome (a
    plain-text-only email, for instance), not an error; callers should
    fall back to extract_posting_urls() on the plain-text body in that
    case -- see get_posting_urls_for_message()."""
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
        normalized = _normalize_linkedin_comm_url(href)
        low = normalized.lower()
        if any(hint in low for hint in _NON_POSTING_URL_HINTS):
            continue
        if any(hint in low for hint in _GENERIC_COLLECTION_URL_HINTS):
            continue
        if any(domain in low for domain in _JOB_POSTING_URL_DOMAINS):
            out.append(normalized)
    return out


def get_message_source(
    account_name: str, message_id: str, mailbox: str = "INBOX"
) -> str | None:
    """Fetches the raw MIME source of one message -- AppleScript's
    `source of msg`, deliberately NOT `content of msg` (see
    get_message_preview()'s docstring: for an HTML email, `content of
    msg` is Mail.app's own plain-text rendering, which keeps visible
    link text but discards every <a href="..."> URL, since the URL only
    ever existed in markup that rendering strips). This is the only way
    to recover a job-alert digest's real per-job listing links -- see
    extract_html_source_urls(), which is what callers should decode this
    with rather than reading it directly.

    Same "search broadly, don't assume Inbox is still where it landed"
    mailbox fallback as get_message_preview() (tries `mailbox` first,
    then scans every other mailbox on the account before giving up), and
    the same lazy/on-demand-only call discipline: called once per
    job-alert-classified message during sync (_extract_and_store_job_
    postings) and once per posting-kind discovery preview -- never
    eagerly for every message in a mailbox scan.

    Returns the full raw MIME text (headers + body, still
    Content-Transfer-Encoding-encoded -- see extract_html_source_urls()
    for decoding), or None if the message can no longer be found
    anywhere in the account (e.g. deleted since the scan that discovered
    it)."""
    resolve_box = _resolve_mailbox_script(mailbox)
    escaped_id = _escape_applescript_string(message_id)
    escaped_account = _escape_applescript_string(account_name)

    script = f"""
    tell application "Mail"
        set acct to account "{escaped_account}"
        set msg to missing value
        try
            {resolve_box}
            set matchedMsgs to (messages of targetBox whose message id is "{escaped_id}")
            if (count of matchedMsgs) > 0 then set msg to item 1 of matchedMsgs
        end try
        if msg is missing value then
            repeat with mb in (every mailbox of acct)
                try
                    set otherMsgs to (messages of mb whose message id is "{escaped_id}")
                    if (count of otherMsgs) > 0 then
                        set msg to item 1 of otherMsgs
                        exit repeat
                    end if
                end try
            end repeat
        end if
        if msg is missing value then return "JOBTRACKER_NOT_FOUND"
        set msgSource to ""
        try
            set msgSource to source of msg
        end try
        return msgSource
    end tell
    """
    raw = _run_applescript(script, timeout=30)
    if not raw or raw == "JOBTRACKER_NOT_FOUND":
        return None
    return raw


def get_posting_urls_for_message(
    account_name: str,
    message_id: str,
    mailbox: str = "INBOX",
    fallback_body: str | None = None,
) -> list[str]:
    """The function callers should use to get real per-job listing links
    out of a message -- tries the raw-MIME-source path first
    (get_message_source() + extract_html_source_urls(), which recovers
    links an HTML email's markup carries that Mail.app's plain-text
    `content of msg` rendering throws away entirely), and only falls
    back to extract_posting_urls(fallback_body) (the plain-text URL
    regex) when the source fetch fails outright (MailAppError -- a
    permission/timeout hiccup shouldn't block the fallback) or the HTML
    source genuinely contains no matching links (a plain-text-only
    email, or an ATS that emails a bare URL instead of an <a> tag).

    `fallback_body` should be the plain-text body the caller already has
    on hand from get_message_preview() -- passed in rather than
    refetched here, since re-fetching it would double the Apple Events
    per message for no benefit.

    Returns [] if neither path finds anything, or the message is gone
    from the account entirely."""
    try:
        raw_source = get_message_source(account_name, message_id, mailbox)
    except MailAppError:
        raw_source = None

    if raw_source:
        urls = extract_html_source_urls(raw_source)
        if urls:
            return urls

    return extract_posting_urls(fallback_body)


def guess_company_from_email(subject: str | None, sender: str | None) -> str | None:
    """Best-effort employer-name guess for the discovery review queue --
    never authoritative, always shown to the user as an editable field
    before anything is created (see api.py's /api/discoveries/{id}/accept).
    Tries a couple of common subject phrasings first ("Your application
    to Acme", "Thank you for applying to Acme") since the subject is
    usually written by (or templated for) the actual employer; falls back
    to the sender's domain, skipping known ATS/webmail domains that would
    only produce a fake "company" name like "Myworkday" or "Gmail"."""
    import re

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

    if sender:
        m = re.search(r"@([\w.-]+)", sender)
        if m:
            domain = m.group(1).lower()
            if domain not in _GENERIC_SENDER_DOMAINS:
                label = domain.split(".")[0]
                if label:
                    return label.replace("-", " ").title()

    return None


def search_unmatched_messages(
    account_name: str,
    known_terms: list[str],
    mailbox: str = "INBOX",
    limit: int = 40,
    always_posting_senders: list[str] | None = None,
) -> list[dict]:
    """Scans this account's mailbox for messages that *look* like
    application-related mail (via _ATS_SUBJECT_PHRASES /
    _ATS_SENDER_DOMAINS) but whose subject/sender doesn't already contain
    any of `known_terms` -- i.e. candidates for applications you haven't
    logged in the tracker yet, as opposed to search_messages()'s job of
    finding new emails for an application you already have. `known_terms`
    should be every open application's company + role terms combined, so
    a message that would already match an existing item during a normal
    sync never shows up here too.

    Like search_messages(), the ATS-phrase filtering happens inside one
    Mail.app `whose` clause (a single Apple Event) rather than iterating
    every message in Python -- see search_messages()'s docstring, point 1,
    for why that matters against a real several-hundred-message inbox.
    The known_terms exclusion happens afterward, in Python, on the (small)
    matched set: building a second whose-clause with a `not` for every one
    of a ~100+ item tracker's terms would make the AppleScript itself
    enormous and slow to construct, for no real benefit since the ATS
    filter has already cut the candidate set down to a handful of
    messages.

    The `whose` condition itself has three parts (see the domain/phrase
    split above _ATS_SENDER_DOMAINS): any ATS subject phrase; sender from
    a pure-ATS domain; or sender from a mixed-signal domain (LinkedIn,
    Indeed, ZipRecruiter) *and* an ATS subject phrase -- then a final
    `and not (...)` strips anything whose subject still looks like a
    bulk job-alert digest regardless of which branch matched it.

    `always_posting_senders` (see overrides_store.list_job_posting_senders,
    discoveries-sender-classification-and-digests-spec.md Part 5.5a) adds
    a fourth `whose`-branch -- `sender contains "..."` per entry, OR'd in
    -- so a message from a whitelisted sender is captured in this same
    single Apple Event, and bypasses BOTH the ATS-subject-phrase gate and
    the digest-subject exclusion entirely. That's the whole point of the
    whitelist: a sender the user has confirmed always sends postings
    (e.g. LinkedIn Job Alerts, whose digest renames the subject to
    whatever listing ranks first) would otherwise never contain an ATS
    phrase and would otherwise always look like a digest -- meaning a
    digest sender could never reach this queue at all on a first sync, so
    there'd be no card to whitelist it from in the first place. The Email
    Sync page's manual "add sender" field (see api.add_job_posting_
    sender_classification) closes that gap: typing the sender's address
    directly whitelists it before any of its mail has ever matched.  Each
    returned hit reports whether it matched via this whitelist as
    \"force_posting\", so the caller can classify it kind=\"posting\"
    unconditionally instead of consulting is_job_posting_style_subject().

    Returns [{\"message_id\", \"subject\", \"sender\", \"received_at\",
    \"guessed_company\", \"force_posting\"}, ...], newest-unfiltered order
    Mail.app's mailbox storage returns them in (not guaranteed most-
    recent-first -- same caveat as search_messages()).
    """
    escaped_phrases = [_escape_applescript_string(p) for p in _ATS_SUBJECT_PHRASES]
    escaped_ats_only_domains = [_escape_applescript_string(d) for d in _ATS_ONLY_SENDER_DOMAINS]
    escaped_mixed_domains = [_escape_applescript_string(d) for d in _MIXED_SIGNAL_SENDER_DOMAINS]
    escaped_digest_phrases = [_escape_applescript_string(p) for p in _DIGEST_SUBJECT_PHRASES]

    subject_conds = [f'subject contains "{p}"' for p in escaped_phrases]
    any_ats_subject = "(" + " or ".join(subject_conds) + ")"

    # Pure-ATS domains: sender alone is enough signal (see
    # _ATS_ONLY_SENDER_DOMAINS's docstring above).
    ats_only_sender_conds = [f'sender contains "{d}"' for d in escaped_ats_only_domains]
    # Mixed-signal domains (LinkedIn, Indeed, ZipRecruiter): also send
    # bulk job-alert digests from the same address, so require the
    # subject to look application-related too, not sender alone.
    mixed_sender_conds = [
        f'(sender contains "{d}" and {any_ats_subject})' for d in escaped_mixed_domains
    ]

    positive_condition = " or ".join(subject_conds + ats_only_sender_conds + mixed_sender_conds)

    # Fourth branch: user-whitelisted senders (see docstring above).
    # `contains`, not exact `is` -- entries reach this list two ways: (a)
    # clicking "always treat as postings" on an existing discovery card,
    # which stores that message's exact raw `sender` field (e.g. "LinkedIn
    # Job Alerts <jobalerts-noreply@linkedin.com>"), where `contains` still
    # matches it as a full-string substring of itself; and (b) a user
    # manually typing just the address (e.g. "jobalerts-noreply@
    # linkedin.com") via the Email Sync "add sender" field, which has no
    # way to know Mail.app's exact display-name formatting and would never
    # match under exact `is`. Still address-scoped, not domain-scoped, so
    # a human recruiter at the same domain (e.g. a real person
    # @linkedin.com) is never accidentally swept in -- see
    # overrides_store.add_job_posting_sender's docstring.
    clean_posting_senders = {s.strip() for s in (always_posting_senders or []) if s and s.strip()}
    escaped_posting_senders = [_escape_applescript_string(s) for s in clean_posting_senders]
    whitelist_sender_conds = [f'sender contains "{s}"' for s in escaped_posting_senders]
    whitelist_condition = "(" + " or ".join(whitelist_sender_conds) + ")" if whitelist_sender_conds else None

    # Even a message that matched the above can still be a bulk digest
    # (e.g. a mixed-signal sender whose subject happens to contain
    # "interview" as part of a listing title) -- exclude anything whose
    # subject carries a digest-style phrasing, as a backstop that isn't
    # tied to any particular sender domain. A whitelisted sender skips
    # this exclusion entirely -- see docstring above.
    digest_exclusion_conds = [f'subject contains "{p}"' for p in escaped_digest_phrases]
    digest_exclusion = f"not ({' or '.join(digest_exclusion_conds)})"
    if whitelist_condition:
        condition = (
            f"(({positive_condition}) or {whitelist_condition}) "
            f"and ({whitelist_condition} or {digest_exclusion})"
        )
    else:
        condition = f"({positive_condition}) and {digest_exclusion}"

    resolve_box = _resolve_mailbox_script(mailbox)

    script = f"""
    tell application "Mail"
        set acct to account "{_escape_applescript_string(account_name)}"
        {resolve_box}
        set matchedMsgs to (messages of targetBox whose {condition})
        set hits to {{}}
        set n to 0
        repeat with msg in matchedMsgs
            set msgId to "unknown"
            try
                set msgId to message id of msg
            end try
            set msgSubject to ""
            try
                set msgSubject to subject of msg
            end try
            set msgSender to ""
            try
                set msgSender to sender of msg
            end try
            set msgDate to ""
            try
                set msgDate to (date received of msg) as string
            end try
            set end of hits to msgId & "|||" & msgSubject & "|||" & msgSender & "|||" & msgDate
            set n to n + 1
            if n \u2265 {int(limit) * 3} then exit repeat
        end repeat
        set AppleScript's text item delimiters to "\\n"
        set hitsStr to hits as text
        set AppleScript's text item delimiters to ""
        return hitsStr
    end tell
    """
    raw = _run_applescript(script, timeout=60)
    if not raw:
        return []

    clean_known_terms = [t.strip() for t in known_terms if t and t.strip()]

    results = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|||")
        if len(parts) != 4:
            continue
        message_id, subject, sender, received_at = parts
        subject = subject.strip()
        sender = sender.strip()

        # Whole-word check, not substring -- see _term_matches_wholeword()'s
        # docstring. A plain substring test here has the same failure
        # shape as search_messages()'s, just inverted: a tracked item's
        # role term of "Tech" would wrongly swallow a genuinely new
        # "Technical Recruiter at Acme" lead into "already tracked"
        # instead of surfacing it for review.
        if any(_term_matches_wholeword(term, subject, sender) for term in clean_known_terms):
            continue  # already matches a tracked item -- normal sync owns this one

        results.append({
            "message_id": message_id.strip() or f"{account_name}:{subject}:{received_at}",
            "subject": subject or None,
            "sender": sender or None,
            "received_at": received_at.strip() or None,
            "guessed_company": guess_company_from_email(subject, sender),
            # Mirrors the AppleScript `contains` check above, not an exact
            # membership test -- a manually-typed whitelist entry (a bare
            # address) is a substring of the real `sender` field here
            # (e.g. "jobalerts-noreply@linkedin.com" in "LinkedIn Job
            # Alerts <jobalerts-noreply@linkedin.com>"), never equal to it.
            "force_posting": any(s in sender for s in clean_posting_senders),
        })
        if len(results) >= limit:
            break
    return results


def get_message_preview(
    account_name: str, message_id: str, mailbox: str = "INBOX", max_chars: int = 4000
) -> str | None:
    """Fetches the plain-text body of one specific message (by the same
    RFC822 Message-ID search_messages()/search_unmatched_messages() key
    everything on), for the discovery review modal's "show me the email"
    view -- so the user can judge a candidate without alt-tabbing into
    Mail.app first. Deliberately lazy/on-demand (called only when a
    review modal opens for one discovery) rather than fetched for every
    row up front: `content of msg` is a second, separate Apple Event per
    message, and the discovery queue can hold dozens of rows -- fetching
    all of them eagerly would multiply an already-slow AppleScript scan
    for a body most rows never get reviewed.

    Returns the body text (truncated to `max_chars`, Mail.app's own
    plain-text extraction of the message -- not raw HTML), or None if no
    message with this id is found in the account at all anymore (e.g. it
    was deleted since the scan that discovered it).

    AUDIT_FINDINGS.md Finding 5: this used to search `mailbox` (default
    "INBOX") only, and return None the moment it wasn't there --
    permanently, since discoveries can sit unreviewed for months and
    Mail.app (or an IMAP provider's own auto-archiving, e.g. Gmail
    marking a thread read/all-mail-only) very plausibly files a message
    out of Inbox well before the user gets to it. Confirmed against real
    usage: some senders' previews load fine, others ("Couldn't load the
    original email") never do, which tracks with per-message mailbox
    drift rather than any error in the fetch itself. Now falls back to
    scanning every other mailbox of the account before giving up, same
    "search broadly, don't assume Inbox is still where it landed"
    principle already used by search_messages()/search_unmatched_messages()."""
    resolve_box = _resolve_mailbox_script(mailbox)
    escaped_id = _escape_applescript_string(message_id)
    escaped_account = _escape_applescript_string(account_name)

    script = f"""
    tell application "Mail"
        set acct to account "{escaped_account}"
        set msg to missing value
        try
            {resolve_box}
            set matchedMsgs to (messages of targetBox whose message id is "{escaped_id}")
            if (count of matchedMsgs) > 0 then set msg to item 1 of matchedMsgs
        end try
        if msg is missing value then
            repeat with mb in (every mailbox of acct)
                try
                    set otherMsgs to (messages of mb whose message id is "{escaped_id}")
                    if (count of otherMsgs) > 0 then
                        set msg to item 1 of otherMsgs
                        exit repeat
                    end if
                end try
            end repeat
        end if
        if msg is missing value then return "JOBTRACKER_NOT_FOUND"
        set msgContent to ""
        try
            set msgContent to content of msg
        end try
        if (count of msgContent) > {int(max_chars)} then
            set msgContent to (text 1 thru {int(max_chars)} of msgContent)
        end if
        return msgContent
    end tell
    """
    raw = _run_applescript(script, timeout=30)
    if not raw or raw == "JOBTRACKER_NOT_FOUND":
        return None
    return raw.strip()


def new_account_id() -> str:
    return str(uuid.uuid4())
