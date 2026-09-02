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

import re
import subprocess
import uuid
from email.parser import HeaderParser

import extract

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
_NON_POSTING_URL_HINTS = [
    "unsubscribe", "optout", "opt-out", "preferences", "privacy",
    "terms-of-service", "/track", "utm_",
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
    a fourth `whose`-branch -- exact `sender is "..."` per entry, OR'd in
    -- so a message from a whitelisted sender is captured in this same
    single Apple Event, and bypasses BOTH the ATS-subject-phrase gate and
    the digest-subject exclusion entirely. That's the whole point of the
    whitelist: a sender the user has confirmed always sends postings
    (e.g. LinkedIn Job Alerts, whose digest renames the subject to
    whatever listing ranks first) would otherwise never contain an ATS
    phrase and would otherwise always look like a digest. Each returned
    hit reports whether it matched via this whitelist as \"force_posting\",
    so the caller can classify it kind=\"posting\" unconditionally instead
    of consulting is_job_posting_style_subject().

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

    # Fourth branch: user-whitelisted exact senders (see docstring above).
    # Exact-match, not `contains`, so this only ever captures the specific
    # address the user clicked "always treat as postings" on -- never a
    # different address that happens to share its domain.
    clean_posting_senders = {s.strip() for s in (always_posting_senders or []) if s and s.strip()}
    escaped_posting_senders = [_escape_applescript_string(s) for s in clean_posting_senders]
    whitelist_sender_conds = [f'sender is "{s}"' for s in escaped_posting_senders]
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
            "force_posting": sender in clean_posting_senders,
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
    message with this id is found in the mailbox anymore (e.g. it was
    moved or deleted since the scan that discovered it)."""
    resolve_box = _resolve_mailbox_script(mailbox)
    escaped_id = _escape_applescript_string(message_id)

    script = f"""
    tell application "Mail"
        set acct to account "{_escape_applescript_string(account_name)}"
        {resolve_box}
        set matchedMsgs to (messages of targetBox whose message id is "{escaped_id}")
        if (count of matchedMsgs) = 0 then return "JOBTRACKER_NOT_FOUND"
        set msg to item 1 of matchedMsgs
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
