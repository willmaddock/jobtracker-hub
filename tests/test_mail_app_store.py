"""
Unit tests for mail_app_store.py. Mocks subprocess.run so these pass
on any OS the suite runs on (CI, a non-Mac dev machine) -- there is no
real Mail.app to talk to here, only the parsing/error-handling logic
around osascript's stdout/stderr/returncode.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import mail_app_store as mailapp


def _completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=["osascript"], returncode=returncode, stdout=stdout, stderr=stderr)


def _hit(message_id, subject, sender, received_at, headers=""):
    """Build one search_messages()-format hit record (5 |||-joined
    fields: id, subject, sender, date, raw headers)."""
    return f"{message_id}|||{subject}|||{sender}|||{received_at}|||{headers}"


def _raw_hits(*hits):
    """Join hit records the way search_messages() expects: the ASCII
    Record Separator (0x1e), not a newline -- raw headers can contain
    their own embedded newlines from RFC 5322 folding."""
    return mailapp._HIT_SEPARATOR.join(hits)


def test_list_mail_app_accounts_parses_name_and_email():
    raw = "iCloud|||will@icloud.com\nhotmail|||stumping123@outlook.com\ndevaios12@outlook.com|||devaios12@outlook.com"
    with patch("subprocess.run", return_value=_completed(stdout=raw)):
        accounts = mailapp.list_mail_app_accounts()
    assert accounts == [
        {"name": "iCloud", "email": "will@icloud.com"},
        {"name": "hotmail", "email": "stumping123@outlook.com"},
        {"name": "devaios12@outlook.com", "email": "devaios12@outlook.com"},
    ]


def test_list_mail_app_accounts_empty_when_none_configured():
    with patch("subprocess.run", return_value=_completed(stdout="")):
        assert mailapp.list_mail_app_accounts() == []


def test_osascript_missing_raises_mail_app_error():
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        try:
            mailapp.list_mail_app_accounts()
            assert False, "expected MailAppError"
        except mailapp.MailAppError as e:
            assert "macOS" in str(e)


def test_timeout_raises_mail_app_error():
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=30)):
        try:
            mailapp.list_mail_app_accounts()
            assert False, "expected MailAppError"
        except mailapp.MailAppError as e:
            assert "respond" in str(e).lower()


def test_denied_automation_permission_gets_a_helpful_message():
    denied = _completed(returncode=1, stderr="execution error: Not allowed to send Apple events (-1743)")
    with patch("subprocess.run", return_value=denied):
        try:
            mailapp.list_mail_app_accounts()
            assert False, "expected MailAppPermissionError"
        except mailapp.MailAppPermissionError as e:
            msg = str(e)
            assert "Automation" in msg
            assert "Privacy & Security" in msg
        except mailapp.MailAppError:
            assert False, "should have raised the specific MailAppPermissionError subclass"


def test_other_osascript_failure_passes_through_stderr():
    failure = _completed(returncode=1, stderr="Mail got an error: some other problem")
    with patch("subprocess.run", return_value=failure):
        try:
            mailapp.list_mail_app_accounts()
            assert False, "expected MailAppError"
        except mailapp.MailAppError as e:
            assert "some other problem" in str(e)


def test_search_messages_with_no_terms_short_circuits_without_calling_osascript():
    with patch("subprocess.run") as run:
        assert mailapp.search_messages("hotmail", []) == []
        run.assert_not_called()


def test_search_messages_with_no_terms_but_thread_ids_still_calls_osascript():
    # A no-text-terms call isn't automatically empty -- an item whose
    # only known identity so far is a confirmed thread id (e.g. picked
    # up from an earlier session on a different mailbox) still needs
    # the mailbox scanned so a reply citing that thread id can be
    # found. The AppleScript condition falls back to "true" (scan
    # everything) since there's no text to filter on.
    with patch("subprocess.run", return_value=_completed(stdout="")) as run:
        mailapp.search_messages("hotmail", [], thread_ids=["<earlier@acme.com>"])
    run.assert_called_once()
    script = run.call_args[0][0][2]
    assert "whose true" in script


def test_search_messages_script_uses_record_separator_not_newline():
    with patch("subprocess.run", return_value=_completed(stdout="")) as run:
        mailapp.search_messages("hotmail", ["Acme"])
    script = run.call_args[0][0][2]
    assert mailapp._HIT_SEPARATOR in script
    assert 'text item delimiters to "\\n"' not in script


def test_search_messages_script_fetches_all_headers():
    with patch("subprocess.run", return_value=_completed(stdout="")) as run:
        mailapp.search_messages("hotmail", ["Acme"])
    script = run.call_args[0][0][2]
    assert "all headers of msg" in script


def test_search_messages_parses_hits():
    raw = _raw_hits(
        _hit("<msgid1>", "Interview invite - Acme", "recruiter@acme.com", "Monday, August 24, 2026"),
        _hit("<msgid2>", "Re: Acme application", "will@acme.com", "Tuesday, August 25, 2026"),
    )
    with patch("subprocess.run", return_value=_completed(stdout=raw)) as run:
        hits = mailapp.search_messages("hotmail", ["Acme"])
    assert run.called
    assert len(hits) == 2
    assert hits[0]["subject"] == "Interview invite - Acme"
    assert hits[0]["message_id"] == "<msgid1>"
    assert hits[1]["sender"] == "will@acme.com"
    assert hits[0]["matched_via"] == "text"


def test_search_messages_falls_back_to_synthetic_id_when_blank():
    raw = _hit("", "No message id here", "someone@example.com", "Monday, August 24, 2026")
    with patch("subprocess.run", return_value=_completed(stdout=raw)):
        hits = mailapp.search_messages("hotmail", ["example"])
    assert len(hits) == 1
    assert hits[0]["message_id"]  # never blank, even without a real header
    assert "No message id here" in hits[0]["message_id"]


def test_search_messages_escapes_quotes_in_terms():
    # A term containing a double-quote shouldn't break the generated
    # AppleScript string literal -- just confirm we don't raise building it.
    with patch("subprocess.run", return_value=_completed(stdout="")):
        mailapp.search_messages("hotmail", ['Say "Hi" Inc'])


def test_search_messages_uses_whose_filter_not_a_manual_repeat_test():
    # Regression test for a real timeout hit against a live ~700-message
    # Gmail account: filtering with "whose" runs as one Apple Event
    # inside Mail.app, instead of "repeat with msg in (messages of X)"
    # followed by an "if <condition>" per message, which round-trips an
    # Apple Event per message and is what actually timed out.
    with patch("subprocess.run", return_value=_completed(stdout="")) as run:
        mailapp.search_messages("hotmail", ["Acme"])
    script = run.call_args[0][0][2]  # ["osascript", "-e", script]
    assert "messages of targetBox whose" in script
    assert "repeat with msg in (messages of targetBox)" not in script


def test_search_messages_default_mailbox_tries_inbox_property_first():
    # `inbox of acct` is tried first (works for some accounts), but is
    # wrapped in `try` so a failure doesn't blow up the whole script --
    # see test_search_messages_falls_back_when_inbox_property_fails
    # for the real-world case (a live Gmail *and* a live Hotmail
    # account) where this property alone wasn't enough.
    with patch("subprocess.run", return_value=_completed(stdout="")) as run:
        mailapp.search_messages("hotmail", ["Acme"])
    script = run.call_args[0][0][2]
    assert "inbox of acct" in script
    assert "try" in script


def test_search_messages_default_mailbox_falls_back_to_scanning_mailbox_list():
    # Regression test: `inbox of acct` raised -1728 against two real
    # accounts (Gmail and Hotmail) even after being introduced
    # specifically to fix an earlier -1728 on `mailbox "INBOX" of
    # acct`. Neither property/name alone is reliable, so the generated
    # script must fall back to scanning `every mailbox of acct` by
    # name if the built-in property comes back empty.
    with patch("subprocess.run", return_value=_completed(stdout="")) as run:
        mailapp.search_messages("hotmail", ["Acme"])
    script = run.call_args[0][0][2]
    assert "every mailbox of acct" in script
    assert 'name of mb is "INBOX"' in script


def test_search_messages_raises_no_inbox_error_when_nothing_resolves():
    # If Mail.app's own AppleScript error handler runs the "error"
    # statement our script emits when both lookup strategies fail, the
    # osascript call itself exits non-zero with our marker in stderr --
    # confirm that gets turned into the specific, actionable exception
    # rather than a generic MailAppError.
    failure = _completed(
        returncode=1,
        stderr='execution error: JOBTRACKER_NO_INBOX: no Inbox mailbox found for this account yet (-2700)',
    )
    with patch("subprocess.run", return_value=failure):
        try:
            mailapp.search_messages("hotmail", ["Acme"])
            assert False, "expected MailAppNoInboxError"
        except mailapp.MailAppNoInboxError as e:
            msg = str(e)
            assert "Mail.app" in msg
            assert "sync" in msg.lower() or "again" in msg.lower()
        except mailapp.MailAppError:
            assert False, "should have raised the specific MailAppNoInboxError subclass"


def test_search_messages_custom_mailbox_uses_named_mailbox_with_fallback():
    with patch("subprocess.run", return_value=_completed(stdout="")) as run:
        mailapp.search_messages("hotmail", ["Acme"], mailbox="Archive")
    script = run.call_args[0][0][2]
    assert 'mailbox "Archive" of acct' in script
    assert 'name of mb is "Archive"' in script


# --- search_unmatched_messages / guess_company_from_email --------------------

def test_search_unmatched_messages_filters_out_known_terms():
    raw = "\n".join([
        "<msg1>|||Thank you for applying to Acme Corp|||careers@acme.com|||Aug 24, 2026",
        "<msg2>|||Your application to Beta Inc has been received|||no-reply@myworkday.com|||Aug 25, 2026",
    ])
    with patch("subprocess.run", return_value=_completed(stdout=raw)):
        candidates = mailapp.search_unmatched_messages("hotmail", known_terms=["Acme"])
    # msg1 mentions "Acme", a known term -- already tracked, must be excluded.
    assert len(candidates) == 1
    assert candidates[0]["message_id"] == "<msg2>"
    assert candidates[0]["guessed_company"] == "Beta Inc"


def test_search_unmatched_messages_uses_ats_whose_filter():
    with patch("subprocess.run", return_value=_completed(stdout="")) as run:
        mailapp.search_unmatched_messages("hotmail", known_terms=[])
    script = run.call_args[0][0][2]
    assert "thank you for applying" in script
    assert "myworkday.com" in script
    assert "messages of targetBox whose" in script


def test_search_unmatched_messages_empty_known_terms_returns_all_candidates():
    raw = "<msg1>|||Your application to Acme Corp|||careers@acme.com|||Aug 24, 2026"
    with patch("subprocess.run", return_value=_completed(stdout=raw)):
        candidates = mailapp.search_unmatched_messages("hotmail", known_terms=[])
    assert len(candidates) == 1


def test_search_unmatched_messages_respects_limit():
    raw = "\n".join(
        f"<msg{i}>|||Thank you for applying to Company{i}|||careers@company{i}.com|||Aug 2{i}, 2026"
        for i in range(5)
    )
    with patch("subprocess.run", return_value=_completed(stdout=raw)):
        candidates = mailapp.search_unmatched_messages("hotmail", known_terms=[], limit=2)
    assert len(candidates) == 2


def test_search_unmatched_messages_skips_malformed_lines():
    raw = "not enough pipes\n<msg1>|||Thank you for applying to Acme|||careers@acme.com|||Aug 24, 2026"
    with patch("subprocess.run", return_value=_completed(stdout=raw)):
        candidates = mailapp.search_unmatched_messages("hotmail", known_terms=[])
    assert len(candidates) == 1


def test_guess_company_from_email_prefers_subject_phrasing():
    assert mailapp.guess_company_from_email("Your application to Acme Corp", "careers@acme.com") == "Acme Corp"


def test_guess_company_from_email_falls_back_to_sender_domain():
    assert mailapp.guess_company_from_email(None, "jobs@delta-corp.com") == "Delta Corp"


def test_guess_company_from_email_skips_generic_and_ats_domains():
    assert mailapp.guess_company_from_email(None, "no-reply@myworkday.com") is None
    assert mailapp.guess_company_from_email(None, "jobs@gmail.com") is None


def test_guess_company_from_email_returns_none_when_nothing_to_go_on():
    assert mailapp.guess_company_from_email(None, None) is None
    assert mailapp.guess_company_from_email("", "") is None


# --- mixed-signal domain / digest filtering (LinkedIn Job Alerts false positives) --

def test_search_unmatched_messages_requires_ats_subject_for_mixed_signal_domains():
    """linkedin.com/indeedemail.com/ziprecruiter.com send both real
    application mail and bulk job-alert digests from the same address --
    sender alone must not be enough to flag a candidate for these, unlike
    a pure-ATS domain such as myworkday.com."""
    with patch("subprocess.run", return_value=_completed(stdout="")) as run:
        mailapp.search_unmatched_messages("hotmail", known_terms=[])
    script = run.call_args[0][0][2]
    assert '(sender contains "linkedin.com" and (' in script
    assert '(sender contains "indeedemail.com" and (' in script
    assert '(sender contains "ziprecruiter.com" and (' in script
    # Pure-ATS domains are still sender-alone (no "and" gate attached).
    assert 'sender contains "myworkday.com" or' in script or 'sender contains "myworkday.com")' in script


def test_search_unmatched_messages_excludes_digest_style_subjects():
    with patch("subprocess.run", return_value=_completed(stdout="")) as run:
        mailapp.search_unmatched_messages("hotmail", known_terms=[])
    script = run.call_args[0][0][2]
    assert "and not (" in script
    assert 'subject contains "job alert"' in script
    assert 'subject contains "new jobs in"' in script


# --- Part 5.5a: job-posting sender whitelist --------------------------------

def test_search_unmatched_messages_adds_a_whitelist_whose_branch_for_posting_senders():
    """A whitelisted sender's exact-match condition should be OR'd into
    the same single `whose` clause -- one Apple Event, not a second
    pass -- and the AppleScript should also gate the digest exclusion so
    that sender bypasses it entirely."""
    sender = "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>"
    with patch("subprocess.run", return_value=_completed(stdout="")) as run:
        mailapp.search_unmatched_messages("hotmail", known_terms=[], always_posting_senders=[sender])
    script = run.call_args[0][0][2]
    assert f'sender is "{sender}"' in script
    assert "messages of targetBox whose" in script
    # Only one whose-clause construction -- no separate second scan.
    assert script.count("messages of targetBox whose") == 1


def test_search_unmatched_messages_with_no_whitelist_omits_the_sender_is_branch():
    with patch("subprocess.run", return_value=_completed(stdout="")) as run:
        mailapp.search_unmatched_messages("hotmail", known_terms=[])
    script = run.call_args[0][0][2]
    assert "sender is " not in script


def test_search_unmatched_messages_reports_force_posting_for_a_whitelisted_sender_hit():
    """This is the actual Haystack-digest regression: a subject with NO
    ATS phrase at all (LinkedIn renamed it to the top listing's title),
    from a whitelisted sender -- force_posting must be True so the
    caller classifies it kind='posting' unconditionally, independent of
    is_job_posting_style_subject()."""
    sender = "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>"
    raw = f"<haystack-1>|||Software Engineer at Haystack|||{sender}|||Sep 1, 2026"
    with patch("subprocess.run", return_value=_completed(stdout=raw)):
        candidates = mailapp.search_unmatched_messages(
            "hotmail", known_terms=[], always_posting_senders=[sender],
        )
    assert len(candidates) == 1
    assert candidates[0]["force_posting"] is True
    assert not mailapp.is_job_posting_style_subject(candidates[0]["subject"])


def test_search_unmatched_messages_non_whitelisted_hit_reports_force_posting_false():
    raw = "<msg1>|||Thank you for applying to Acme|||careers@acme.com|||Aug 24, 2026"
    with patch("subprocess.run", return_value=_completed(stdout=raw)):
        candidates = mailapp.search_unmatched_messages(
            "hotmail", known_terms=[],
            always_posting_senders=["LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>"],
        )
    assert len(candidates) == 1
    assert candidates[0]["force_posting"] is False


# --- Part 5.5b: extract_posting_urls (multi-listing digests) ---------------

def test_extract_posting_urls_returns_every_matching_link_in_body_order():
    body = (
        "Software Engineer: https://www.linkedin.com/jobs/view/1111\n"
        "Back-End Developer - WFH: https://www.linkedin.com/jobs/view/2222\n"
        "Backend Engineer: https://www.linkedin.com/jobs/view/3333\n"
        "Unsubscribe: https://www.linkedin.com/psettings/unsubscribe?x=1\n"
    )
    assert mailapp.extract_posting_urls(body) == [
        "https://www.linkedin.com/jobs/view/1111",
        "https://www.linkedin.com/jobs/view/2222",
        "https://www.linkedin.com/jobs/view/3333",
    ]


def test_extract_posting_urls_dedupes_while_preserving_order():
    body = (
        "https://boards.greenhouse.io/acme/jobs/1\n"
        "https://boards.greenhouse.io/acme/jobs/2\n"
        "https://boards.greenhouse.io/acme/jobs/1\n"
    )
    assert mailapp.extract_posting_urls(body) == [
        "https://boards.greenhouse.io/acme/jobs/1",
        "https://boards.greenhouse.io/acme/jobs/2",
    ]


def test_extract_posting_urls_returns_empty_list_for_empty_or_none_body():
    assert mailapp.extract_posting_urls(None) == []
    assert mailapp.extract_posting_urls("") == []


def test_extract_posting_urls_returns_empty_list_when_nothing_recognizable():
    assert mailapp.extract_posting_urls("Visit our site: https://comcast.com") == []


def test_guess_posting_url_still_returns_just_the_first_link_for_backward_compat():
    body = (
        "https://www.linkedin.com/jobs/view/1111\n"
        "https://www.linkedin.com/jobs/view/2222\n"
    )
    assert mailapp.guess_posting_url(body) == "https://www.linkedin.com/jobs/view/1111"


def test_search_unmatched_messages_filters_out_linkedin_job_alert_digest():
    """End-to-end regression for the exact false positive seen in
    practice: a 'LinkedIn Job Alerts' digest ('Your job alert for back
    end developer ... New jobs in Denver Metropolitan Area match your
    preferences') must not surface as a discovery candidate, even though
    it's from linkedin.com and its subject happens to contain a company
    name that looks like a real application. Mail.app's own `whose`
    filtering (mocked here) is what actually excludes it -- this test
    documents the intent and guards the AppleScript condition string
    that drives it."""
    with patch("subprocess.run", return_value=_completed(stdout="")) as run:
        mailapp.search_unmatched_messages("hotmail", known_terms=[])
    script = run.call_args[0][0][2]
    # The digest subject contains neither an ATS phrase nor gets past the
    # "and not (job alert / new jobs in / ...)" exclusion, so a message
    # with subject "Your job alert for back end developer" -- sent from
    # linkedin.com -- fails both the mixed-signal gate (no ATS phrase in
    # subject) and would additionally be excluded by the digest phrases
    # even if it somehow matched. Assert both halves of that protection
    # are present in the generated condition.
    assert 'subject contains "job alert"' in script
    assert '(sender contains "linkedin.com" and (' in script


# --- is_job_posting_style_subject -----------------------------------------

def test_is_job_posting_style_subject_matches_percent_match_phrasing():
    assert mailapp.is_job_posting_style_subject(
        "KPMG US just posted a 78% match Front End Engineer- Associate role"
    )


def test_is_job_posting_style_subject_matches_comcast_new_jobs_open():
    assert mailapp.is_job_posting_style_subject(
        "Comcast just posted a 80% match Junior DevOps / SRE 2 - Chicago, IL"
    )
    assert mailapp.is_job_posting_style_subject("Just in: Comcast has new Junior Developer jobs open")


def test_is_job_posting_style_subject_false_for_ordinary_application_subject():
    assert not mailapp.is_job_posting_style_subject("Your application to Acme Corp")
    assert not mailapp.is_job_posting_style_subject("Thank you for applying to Acme")


def test_is_job_posting_style_subject_false_for_none_or_empty():
    assert not mailapp.is_job_posting_style_subject(None)
    assert not mailapp.is_job_posting_style_subject("")


# --- get_message_preview -------------------------------------------------

def test_get_message_preview_returns_body_text():
    with patch("subprocess.run", return_value=_completed(stdout="Hi Will, thanks for applying...")):
        body = mailapp.get_message_preview("hotmail", "<msg1>")
    assert body == "Hi Will, thanks for applying..."


def test_get_message_preview_returns_none_when_message_not_found():
    with patch("subprocess.run", return_value=_completed(stdout="JOBTRACKER_NOT_FOUND")):
        body = mailapp.get_message_preview("hotmail", "<gone>")
    assert body is None


def test_get_message_preview_escapes_message_id_in_script():
    with patch("subprocess.run", return_value=_completed(stdout="")) as run:
        mailapp.get_message_preview("hotmail", 'weird"id')
    script = run.call_args[0][0][2]
    assert 'message id is "weird\\"id"' in script


# --- is_usable_match_term -------------------------------------------------
# Regression coverage for the over-matching bug: a short/generic term (a
# role label of "IT", "(root)", etc.) used to be OR'd straight into the
# AppleScript `contains` filter and matched huge amounts of unrelated mail.

def test_is_usable_match_term_rejects_short_terms():
    assert mailapp.is_usable_match_term("IT") is False
    assert mailapp.is_usable_match_term("PM") is False
    assert mailapp.is_usable_match_term("Q1") is False


def test_is_usable_match_term_rejects_generic_stoplist_terms():
    assert mailapp.is_usable_match_term("dev") is False
    assert mailapp.is_usable_match_term("Root") is False
    assert mailapp.is_usable_match_term("(root)") is False
    assert mailapp.is_usable_match_term("TBD") is False


def test_is_usable_match_term_accepts_specific_terms():
    assert mailapp.is_usable_match_term("Adams County") is True
    assert mailapp.is_usable_match_term("Data Engineer") is True
    assert mailapp.is_usable_match_term("Slalom") is True


def test_is_usable_match_term_rejects_empty_or_none():
    assert mailapp.is_usable_match_term(None) is False
    assert mailapp.is_usable_match_term("") is False
    assert mailapp.is_usable_match_term("   ") is False


# --- word-boundary matching (search_messages / search_unmatched_messages) --
# Regression coverage for a second, distinct over-matching bug found after
# the is_usable_match_term() fix above shipped: a term that's long enough
# and not on the generic stoplist -- e.g. a role label of "Tech" -- still
# passes is_usable_match_term(), but Mail.app's `contains` operator is a
# plain substring test with no word-boundary awareness, so it also matches
# the middle of unrelated words ("Technical", "Biotech"). Confirmed against
# a real tracker: a "Metro Water Recovery / Tech" item picked up "Technical
# Project Manager at Ladders", "... at StrataBlue", and other listings that
# have nothing to do with Metro Water Recovery. search_messages() and
# search_unmatched_messages() now re-check every AppleScript hit in Python
# with _term_matches_wholeword() before trusting it.

def test_term_matches_wholeword_rejects_midword_substring():
    assert mailapp._term_matches_wholeword("Tech", "Technical Project Manager") is False
    assert mailapp._term_matches_wholeword("Tech", "Biotech Solutions") is False


def test_term_matches_wholeword_accepts_standalone_word():
    assert mailapp._term_matches_wholeword("Tech", "Following up on your Tech application") is True
    assert mailapp._term_matches_wholeword("Tech", "TECH ROLE - interview") is True


def test_term_matches_wholeword_checks_multiple_texts():
    assert mailapp._term_matches_wholeword("Acme", "unrelated subject", "recruiter@acme.com") is True
    assert mailapp._term_matches_wholeword("Acme", None, "recruiter@acme.com") is True


def test_search_messages_drops_a_hit_that_only_substring_matched():
    # Regression test for the exact real-world case: a "Tech" role term
    # should not attach "Technical Project Manager at Ladders" or "...at
    # StrataBlue" to a Metro Water Recovery application, but a subject that
    # actually contains "Metro Water Recovery" should still come through.
    raw = _raw_hits(
        _hit("<id1>", "Technical Project Manager at Ladders: up to $120K/year", "jobs@ladders.com", "Mon"),
        _hit("<id2>", "Technical Project Manager ($60k-$80k) at StrataBlue", "noreply@strata.com", "Tue"),
        _hit("<id3>", "Metro Water Recovery Tech interview scheduled", "hr@metrowater.org", "Wed"),
    )
    with patch("subprocess.run", return_value=_completed(stdout=raw)):
        hits = mailapp.search_messages("hotmail", ["Metro Water Recovery", "Tech"])
    assert len(hits) == 1
    assert "Metro Water Recovery" in hits[0]["subject"]


def test_search_messages_still_matches_term_as_a_standalone_word():
    raw = _hit("<id1>", "Following up on your Tech application", "hr@acme.com", "Thu")
    with patch("subprocess.run", return_value=_completed(stdout=raw)):
        hits = mailapp.search_messages("hotmail", ["Tech"])
    assert len(hits) == 1


# --- role-only hits shouldn't confirm identity on their own -----------------
# Word-boundary matching (above) stops a role term from matching mid-word
# ("Technical"), but a role term that's a perfectly ordinary standalone
# word is still not a safe identity confirmation by itself. Confirmed
# live, post-word-boundary-fix, against a real tracker: a "Home Depot /
# Resume" item's role term "Resume" whole-word-matched "Your resume was
# received by Claritev" (a different company entirely), and a "Metro
# Water Recovery / Tech" item's role term "Tech" whole-word-matched
# "Project Manager (Non Tech) at ... (WMATA)" (also unrelated). Passing
# role_terms tells search_messages() which terms are role labels, so a
# hit only counts if the company term matched too (or there was no
# company term to check against).

def test_search_messages_rejects_role_only_hit_when_company_term_available():
    raw = _hit("<id1>", "Your resume was received by Claritev", "noreply@claritev.com", "Mon")
    with patch("subprocess.run", return_value=_completed(stdout=raw)):
        hits = mailapp.search_messages(
            "hotmail", ["Home Depot", "Resume"], role_terms=["Resume"]
        )
    assert hits == []


def test_search_messages_rejects_role_only_hit_metro_water_tech_case():
    raw = _hit(
        "<id1>", "Project Manager (Non Tech) at Washington Metropolitan Area Transit Authority (WMATA)",
        "jobs@wmata.com", "Tue",
    )
    with patch("subprocess.run", return_value=_completed(stdout=raw)):
        hits = mailapp.search_messages(
            "hotmail", ["Metro Water Recovery", "Tech"], role_terms=["Tech"]
        )
    assert hits == []


def test_search_messages_still_accepts_role_hit_when_company_also_matches():
    raw = _hit("<id1>", "Metro Water Recovery Tech interview scheduled", "hr@metrowater.org", "Wed")
    with patch("subprocess.run", return_value=_completed(stdout=raw)):
        hits = mailapp.search_messages(
            "hotmail", ["Metro Water Recovery", "Tech"], role_terms=["Tech"]
        )
    assert len(hits) == 1


def test_search_messages_falls_back_to_role_only_when_no_company_term_given():
    # role_terms is only enforced when a company term is actually in
    # play (see docstring) -- omitting it keeps the old permissive
    # behavior, e.g. for callers with no usable company term at all.
    raw = _hit("<id1>", "Following up on your Tech application", "hr@acme.com", "Thu")
    with patch("subprocess.run", return_value=_completed(stdout=raw)):
        hits = mailapp.search_messages("hotmail", ["Tech"], role_terms=["Tech"])
    assert len(hits) == 1


def test_search_unmatched_messages_does_not_swallow_a_real_lead_on_substring():
    # Inverse of the bug above: a tracked item's "Tech" role term
    # shouldn't cause search_unmatched_messages() to wrongly treat a
    # genuinely new "Technical Recruiter" lead as already-tracked.
    raw = "<id1>|||Thank you for applying - Technical Recruiter role|||hr@newco.com|||Fri"
    with patch("subprocess.run", return_value=_completed(stdout=raw)):
        candidates = mailapp.search_unmatched_messages(
            "hotmail", known_terms=["Tech", "Metro Water Recovery"]
        )
    assert len(candidates) == 1
    assert "Technical Recruiter" in candidates[0]["subject"]


# --- thread-id header parsing / deterministic reply-matching ---------------
# Header-threading: a reply whose subject/sender share nothing textually
# with the item (e.g. "Re: your submission") still attaches to it once its
# In-Reply-To/References headers cite a Message-ID already confirmed for
# that item on a prior sync. See search_messages()'s docstring and
# mail_app_store._extract_thread_message_ids().

def test_extract_thread_message_ids_parses_in_reply_to_and_references():
    headers = (
        "Message-ID: <reply1@gmail.com>\n"
        "In-Reply-To: <original@acme.com>\n"
        "References: <original@acme.com> <middle@acme.com>\n"
    )
    ids = mailapp._extract_thread_message_ids(headers)
    assert ids == {"<original@acme.com>", "<middle@acme.com>"}


def test_extract_thread_message_ids_handles_folded_references_header():
    # A long thread's References header routinely wraps across several
    # physical lines (RFC 5322 folding) -- confirm HeaderParser un-folds
    # it before token extraction rather than losing the continuation.
    headers = (
        "Message-ID: <reply2@gmail.com>\n"
        "References: <one@acme.com>\n"
        " <two@acme.com>\n"
        " <three@acme.com>\n"
    )
    ids = mailapp._extract_thread_message_ids(headers)
    assert ids == {"<one@acme.com>", "<two@acme.com>", "<three@acme.com>"}


def test_extract_thread_message_ids_empty_or_missing_headers_returns_empty_set():
    assert mailapp._extract_thread_message_ids("") == set()
    assert mailapp._extract_thread_message_ids("Subject: no thread headers here\n") == set()


def test_search_messages_every_hit_reports_its_own_thread_message_ids():
    headers = "Message-ID: <msgid1>\nReferences: <earlier@acme.com>\n"
    raw = _hit("<msgid1>", "Interview invite - Acme", "recruiter@acme.com", "Mon", headers)
    with patch("subprocess.run", return_value=_completed(stdout=raw)):
        hits = mailapp.search_messages("hotmail", ["Acme"])
    assert len(hits) == 1
    assert set(hits[0]["thread_message_ids"]) == {"<msgid1>", "<earlier@acme.com>"}


def test_search_messages_matches_a_reply_via_thread_id_with_no_text_overlap():
    # The core scenario: subject/sender share nothing with "Acme" or any
    # role term, but In-Reply-To cites a Message-ID already confirmed
    # for this item -- must still be trusted, and reported as such.
    headers = "Message-ID: <reply@gmail.com>\nIn-Reply-To: <earlier@acme.com>\n"
    raw = _hit("<reply@gmail.com>", "Re: your submission", "recruiter@acme.com", "Tue", headers)
    with patch("subprocess.run", return_value=_completed(stdout=raw)):
        hits = mailapp.search_messages("hotmail", ["Acme"], thread_ids=["<earlier@acme.com>"])
    assert len(hits) == 1
    assert hits[0]["matched_via"] == "thread"
    assert hits[0]["message_id"] == "<reply@gmail.com>"


def test_search_messages_thread_id_match_bypasses_role_only_rejection():
    # Even a hit that would normally be rejected as role-only (see the
    # Resume/Tech regression tests above) is trusted once it matches via
    # a confirmed thread id -- the whole point of thread matching is to
    # skip the text heuristics entirely for messages headers already
    # confirm belong to this item.
    headers = "Message-ID: <reply@gmail.com>\nIn-Reply-To: <earlier@claritev.com>\n"
    raw = _hit("<reply@gmail.com>", "Your resume was received by Claritev", "noreply@claritev.com", "Wed", headers)
    with patch("subprocess.run", return_value=_completed(stdout=raw)):
        hits = mailapp.search_messages(
            "hotmail", ["Home Depot", "Resume"], role_terms=["Resume"],
            thread_ids=["<earlier@claritev.com>"],
        )
    assert len(hits) == 1
    assert hits[0]["matched_via"] == "thread"


def test_search_messages_thread_ids_that_dont_match_fall_through_to_text_matching():
    # A thread_ids set that just doesn't overlap this message's headers
    # is a no-op -- ordinary text matching still applies.
    raw = _hit("<msgid1>", "Interview invite - Acme", "recruiter@acme.com", "Mon")
    with patch("subprocess.run", return_value=_completed(stdout=raw)):
        hits = mailapp.search_messages("hotmail", ["Acme"], thread_ids=["<unrelated@other.com>"])
    assert len(hits) == 1
    assert hits[0]["matched_via"] == "text"


def test_search_messages_no_text_terms_and_no_thread_match_yields_nothing():
    # A message that neither matches any text term nor cites a known
    # thread id is dropped -- there's nothing left to confirm identity.
    raw = _hit("<msgid1>", "Unrelated newsletter", "noreply@other.com", "Mon")
    with patch("subprocess.run", return_value=_completed(stdout=raw)):
        hits = mailapp.search_messages("hotmail", [], thread_ids=["<earlier@acme.com>"])
    assert hits == []

# --- guess_posting_url ------------------------------------------------------

def test_guess_posting_url_picks_known_ats_link():
    body = (
        "KPMG just posted a new role.\n"
        "Unsubscribe: https://example.com/unsubscribe?id=1\n"
        "View the job: https://boards.greenhouse.io/kpmg/jobs/12345\n"
    )
    assert mailapp.guess_posting_url(body) == "https://boards.greenhouse.io/kpmg/jobs/12345"


def test_guess_posting_url_skips_unsubscribe_even_on_a_known_domain():
    body = "Manage alerts: https://www.linkedin.com/jobs/unsubscribe?x=1"
    assert mailapp.guess_posting_url(body) is None


def test_guess_posting_url_returns_none_when_nothing_recognizable():
    body = "Comcast just posted a new role. Visit our site: https://comcast.com"
    assert mailapp.guess_posting_url(body) is None


def test_guess_posting_url_returns_none_for_empty_or_none_body():
    assert mailapp.guess_posting_url(None) is None
    assert mailapp.guess_posting_url("") is None
