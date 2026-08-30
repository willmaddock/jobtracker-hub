"""
Tests for role_extract.py -- job-posting section extraction (Checkpoint 2).

Covers each real-corpus header style found while building this module
(combined Qualifications/Minimum/Desired split, colon-style headers,
Basic Qualifications/Nice To Have, public-sector Description -> Examples
of Duties -> Qualifications, and the Adams-County-style "for Success"
template), plus the two PDF-rendering quirks (ligatures, duplicated
headers), a nav-line false-positive guard, first-occurrence-wins on a
repeated header, and no-header/empty-text handling.

Standalone module, no workspace state -- just needs sys.path (set up by
conftest.py).
"""

from __future__ import annotations

import role_extract as re_


def test_kroger_style_minimum_desired_split_within_one_qualifications_header():
    text = (
        "JOB DESCRIPTION\n"
        "Perform administrative duties in a fast-paced manufacturing environment.\n"
        "RESPONSIBILITIES\n"
        "- Maintain accurate records\n"
        "- Support the team with day-to-day tasks\n"
        "QUALIFICATIONS\n"
        "Minimum\n"
        "- High School Diploma or GED\n"
        "- Ability to work any shift\n"
        "Desired\n"
        "- Prior administrative experience\n"
    )
    result = re_.extract_role_sections(text)
    assert "manufacturing environment" in result[re_.ROLE_SUMMARY]
    assert "Maintain accurate records" in result[re_.DUTIES]
    assert "High School Diploma" in result[re_.REQUIRED_QUALIFICATIONS]
    assert "Minimum" not in result[re_.REQUIRED_QUALIFICATIONS]
    assert "Prior administrative experience" in result[re_.PREFERRED_QUALIFICATIONS]
    assert "Desired" not in result[re_.PREFERRED_QUALIFICATIONS]


def test_colon_style_headers_no_summary_no_preferred():
    text = (
        "Acme Corp is seeking an Associate Engineer to join our team.\n"
        "Responsibilities:\n"
        "Design, develop, and maintain internal tools\n"
        "Collaborate with cross-functional teams\n"
        "Qualifications:\n"
        "Bachelor's degree in Computer Science or related field\n"
        "1+ years of professional software experience\n"
    )
    result = re_.extract_role_sections(text)
    assert result[re_.ROLE_SUMMARY] == re_.NOT_DETECTED
    assert "Design, develop" in result[re_.DUTIES]
    assert "Bachelor's degree" in result[re_.REQUIRED_QUALIFICATIONS]
    assert result[re_.PREFERRED_QUALIFICATIONS] == re_.NOT_DETECTED


def test_basic_qualifications_and_nice_to_have_style():
    text = (
        "We're seeking a candidate who thrives in ambiguous environments.\n"
        "Basic Qualifications:\n"
        "1-3 years of software development experience\n"
        "Experience operating business-critical systems at scale\n"
        "Nice To Have:\n"
        "Distributed systems experience\n"
        "Familiarity with large-scale data pipelines\n"
    )
    result = re_.extract_role_sections(text)
    assert "1-3 years" in result[re_.REQUIRED_QUALIFICATIONS]
    assert "Distributed systems" in result[re_.PREFERRED_QUALIFICATIONS]


def test_public_sector_description_duties_qualifications_style():
    text = (
        "Metro Utility District\n"
        "IT Service Delivery Analyst I\n"
        "SALARY $27.77 - $37.57 Hourly\n"
        "Description\n"
        "Provides first response to IT support issues for internal staff.\n"
        "Examples of Duties\n"
        "1. Responds to IT support tickets in a timely manner.\n"
        "2. Sets up equipment for new hires.\n"
        "Qualifications\n"
        "Knowledge of Windows operating systems\n"
        "Ability to communicate clearly in writing\n"
    )
    result = re_.extract_role_sections(text)
    assert "first response" in result[re_.ROLE_SUMMARY]
    assert "IT support tickets" in result[re_.DUTIES]
    assert "Windows operating systems" in result[re_.REQUIRED_QUALIFICATIONS]
    assert result[re_.PREFERRED_QUALIFICATIONS] == re_.NOT_DETECTED


def test_for_success_template_style():
    # Adams County's real-corpus template: every header suffixed "for Success".
    text = (
        "What Success Looks Like In This Job\n"
        "The Desktop Support Technician manages end-user computing.\n"
        "Examples of Duties for Success\n"
        "Deploy, configure, update and maintain desktops and laptops.\n"
        "Qualifications for Success\n"
        "Quickly analyze operational issues with complex computer equipment.\n"
    )
    result = re_.extract_role_sections(text)
    assert "end-user computing" in result[re_.ROLE_SUMMARY]
    assert "Deploy, configure" in result[re_.DUTIES]
    assert "operational issues" in result[re_.REQUIRED_QUALIFICATIONS]


def test_curly_apostrophe_header_is_recognized():
    text = "What You\u2019ll Do:\nWrite clean, maintainable code.\nParticipate in code reviews.\n"
    result = re_.extract_role_sections(text)
    assert "Write clean" in result[re_.DUTIES]


def test_ligature_normalization_in_header():
    text = "Minimum Qualiﬁcations \nBachelor's degree in a related field.\n"
    result = re_.extract_role_sections(text)
    assert "Bachelor's degree" in result[re_.REQUIRED_QUALIFICATIONS]


def test_duplicated_header_rendering_artifact_collapses():
    # Some career-site templates render the header repeated with no
    # separator -- seen verbatim in the real corpus (e.g. bet365, Brother).
    text = "Job DescriptionJob DescriptionJob DescriptionJob Description\nBuilds and maintains internal tooling.\n"
    result = re_.extract_role_sections(text)
    assert "internal tooling" in result[re_.ROLE_SUMMARY]


def test_no_recognizable_headers_reports_not_detected_for_everything():
    text = "Thank you for your interest in this role. We'll be in touch soon.\n"
    result = re_.extract_role_sections(text)
    assert all(result[k] == re_.NOT_DETECTED for k in re_.SECTION_KEYS)


def test_empty_text_reports_not_detected_for_everything():
    result = re_.extract_role_sections("")
    assert all(result[k] == re_.NOT_DETECTED for k in re_.SECTION_KEYS)


def test_long_nav_line_is_not_a_false_positive_header():
    # A line that merely *contains* header words shouldn't match -- only a
    # line that IS (after trimming/colon-stripping) one of the canonical
    # header phrases counts.
    text = (
        "Vaccination Status Requirements Providers Jobs Cookie Management\n"
        "Description\n"
        "Builds internal dashboards for the analytics team.\n"
    )
    result = re_.extract_role_sections(text)
    assert "internal dashboards" in result[re_.ROLE_SUMMARY]


def test_first_occurrence_of_a_repeated_header_wins():
    text = (
        "Responsibilities\n"
        "First duties block.\n"
        "Responsibilities\n"
        "Second duties block (should not overwrite the first).\n"
    )
    result = re_.extract_role_sections(text)
    assert "First duties block" in result[re_.DUTIES]
    assert "Second duties block" not in result[re_.DUTIES]


def test_empty_role_sections_shape():
    result = re_.empty_role_sections()
    assert set(result.keys()) == set(re_.SECTION_KEYS)
    assert all(v == re_.NOT_DETECTED for v in result.values())
