"""
Tests for date_extract.py -- the Checkpoint 5 date-applied evidence
detection. See its module docstring for the two patterns tried and why.
"""

from __future__ import annotations

import date_extract


def test_email_header_full_month_with_time_suffix():
    text = (
        "From: no-reply@us.greenhouse-mail.io\n"
        "Subject: Thank you for applying to Extend\n"
        "Date: July 10, 2025 at 10:56 AM\n"
        "To: candidate@example.com\n"
        "Thanks for applying to Extend.\n"
    )
    assert date_extract.extract_application_date(text) == "2025-07-10"


def test_email_header_abbreviated_month_no_time_suffix():
    text = "Date: Date: Date: Jul 30, 2025\nSome scraped page content.\n"
    assert date_extract.extract_application_date(text) == "2025-07-30"


def test_email_header_takes_first_match_when_multiple_date_lines():
    # A forwarded/threaded email print can have more than one "Date:"
    # line -- the first one found (the outermost/most recent message)
    # wins, since that's the one most likely to represent this
    # confirmation's own timestamp.
    text = (
        "Date: September 24, 2025 at 6:00 PM\n"
        "...\n"
        "Date: September 20, 2025 at 9:00 AM\n"
    )
    assert date_extract.extract_application_date(text) == "2025-09-24"


def test_keyworded_slash_date_fallback_when_no_email_header():
    text = (
        "Dear William Maddock,\n"
        "Your application has been received by Front Range Community "
        "College for the Part-Time Professional Tester position at "
        "09/24/2025 06:00 PM Mountain Time (US & Canada)\n"
    )
    assert date_extract.extract_application_date(text) == "2025-09-24"


def test_slash_date_far_from_any_keyword_is_not_matched():
    # A job ID or unrelated date elsewhere in the document should not be
    # mistaken for an application date just because it happens to follow
    # "received" somewhere much earlier in the same sentence/paragraph.
    text = "We received your resume. " + ("Filler text here. " * 15) + "Posted 09/24/2025."
    assert date_extract.extract_application_date(text) is None


def test_no_recognizable_pattern_returns_none():
    assert date_extract.extract_application_date("Just a resume with no dates.") is None


def test_empty_text_returns_none():
    assert date_extract.extract_application_date("") is None


def test_invalid_calendar_date_is_rejected_not_guessed():
    # Day 32 doesn't exist in any month -- a false-positive-shaped match
    # must not be coerced into something plausible-looking.
    text = "Date: February 32, 2025 at 1:00 PM\n"
    assert date_extract.extract_application_date(text) is None
