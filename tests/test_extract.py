"""
Tests for extract.py -- the Item 6 extraction foundation.

Covers: deterministic email/phone/URL regex extraction, text extraction
from .pdf/.txt files (including failure cases), path-traversal safety,
and the content_hash-keyed cache wrapper in overrides_store.py.

Does not depend on the app/workspace fixtures in conftest.py -- extract.py
and overrides_store.py are standalone modules with no workspace state, so
these tests just need sys.path (already set up by conftest.py) plus their
own tmp_path fixtures.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import extract
import overrides_store as ov
import role_extract

FIXTURES = Path(__file__).parent / "fixtures"


# --- contact regex extraction -------------------------------------------------

def test_extract_emails_finds_and_dedupes_case_insensitively():
    text = "Contact Jane at Jane.Doe@Acme.com or jane.doe@acme.com for details."
    emails = extract.extract_emails(text)
    assert emails == ["Jane.Doe@Acme.com"]


def test_extract_emails_ignores_trailing_punctuation():
    text = "Reach out to recruiter@acme.com. Thanks!"
    assert extract.extract_emails(text) == ["recruiter@acme.com"]


def test_extract_phones_handles_multiple_formats_and_dedupes():
    text = (
        "Call (303) 555-1234 or 303-555-1234 or 303.555.1234 "
        "or the office line at +1 720 555 9876."
    )
    phones = extract.extract_phones(text)
    # first three are the same number in different formats -> one entry
    assert len(phones) == 2
    assert any("303" in p for p in phones)
    assert any("720" in p for p in phones)


def test_extract_phones_does_not_false_positive_on_job_ids_or_zip_codes():
    text = "Job ID 2894707. Denver, CO 80202-1234. Requisition #123456789."
    assert extract.extract_phones(text) == []


def test_extract_urls_finds_http_and_www_and_strips_trailing_punctuation():
    text = "Apply at https://acme.com/careers/1234, or see www.acme.com/jobs."
    urls = extract.extract_urls(text)
    assert urls == ["https://acme.com/careers/1234", "www.acme.com/jobs"]


def test_extract_contacts_bundles_all_three():
    text = "Email hr@acme.com, call 303-555-1234, visit https://acme.com"
    result = extract.extract_contacts(text)
    assert result["emails"] == ["hr@acme.com"]
    assert result["phones"] == ["303-555-1234"]
    assert result["urls"] == ["https://acme.com"]


def test_extract_contacts_empty_text_returns_empty_lists():
    result = extract.extract_contacts("")
    assert result == {"emails": [], "phones": [], "urls": []}


# --- file text extraction -----------------------------------------------------

def test_extract_text_from_txt_file(tmp_path):
    p = tmp_path / "notice.txt"
    p.write_text("Application received. Contact hr@acme.com.", encoding="utf-8")
    text, ok, error = extract.extract_text_from_file(p)
    assert ok is True
    assert error is None
    assert "hr@acme.com" in text


def test_extract_text_from_real_pdf_fixture(tmp_path):
    dest = tmp_path / "job_posting.pdf"
    shutil.copy(FIXTURES / "sample_job_posting.pdf", dest)
    text, ok, error = extract.extract_text_from_file(dest)
    assert ok is True
    assert error is None
    assert "jane.recruiter@acme-corp.com" in text
    assert "555-1234" in text


def test_extract_text_from_corrupt_pdf_fails_gracefully(tmp_path):
    p = tmp_path / "broken.pdf"
    p.write_bytes(b"not actually a pdf")
    text, ok, error = extract.extract_text_from_file(p)
    assert ok is False
    assert text == ""
    assert error  # some message, don't over-specify pypdf's wording


def test_extract_text_unsupported_extension_reports_not_ok(tmp_path):
    p = tmp_path / "notes.docx"
    p.write_bytes(b"fake docx bytes")
    text, ok, error = extract.extract_text_from_file(p)
    assert ok is False
    assert "Unsupported" in error


# --- path safety ---------------------------------------------------------------

def test_resolve_safe_for_root_rejects_path_traversal(tmp_path):
    (tmp_path / "Applications").mkdir()
    with pytest.raises(ValueError, match="escapes"):
        extract.resolve_safe_for_root(tmp_path, "../../../../etc/passwd")


def test_resolve_safe_for_root_rejects_missing_file(tmp_path):
    with pytest.raises(ValueError, match="not found"):
        extract.resolve_safe_for_root(tmp_path, "Applications/nope.pdf")


def test_extract_document_reports_failure_instead_of_raising_on_bad_relpath(tmp_path):
    result = extract.extract_document(tmp_path, "../escape.pdf")
    assert result["extraction_ok"] is False
    assert result["emails"] == []


# --- end-to-end extraction ------------------------------------------------------

def test_extract_document_full_flow(tmp_path):
    apps = tmp_path / "Applications" / "Acme"
    apps.mkdir(parents=True)
    dest = apps / "job_posting.pdf"
    shutil.copy(FIXTURES / "sample_job_posting.pdf", dest)

    result = extract.extract_document(tmp_path, "Applications/Acme/job_posting.pdf")
    assert result["extraction_ok"] is True
    assert result["emails"] == ["jane.recruiter@acme-corp.com"]
    assert result["urls"] == ["https://acme-corp.com/careers/1234"]
    assert result["text_length"] > 0
    # sample_job_posting.pdf has no section headers -- role fields must
    # report "Not detected" rather than fabricate structure that isn't there.
    for key in role_extract.SECTION_KEYS:
        assert result[key] == role_extract.NOT_DETECTED


def test_extract_document_extracts_role_sections_from_job_posting_text(tmp_path):
    apps = tmp_path / "Applications" / "Acme"
    apps.mkdir(parents=True)
    dest = apps / "posting.txt"
    dest.write_text(
        "Job Description\n"
        "Builds internal tools for the platform team.\n"
        "Responsibilities\n"
        "Write and review code.\n"
        "Required Qualifications\n"
        "3+ years of experience.\n"
        "Preferred Qualifications\n"
        "Experience with Kubernetes.\n",
        encoding="utf-8",
    )
    result = extract.extract_document(tmp_path, "Applications/Acme/posting.txt")
    assert result["extraction_ok"] is True
    assert "internal tools" in result[role_extract.ROLE_SUMMARY]
    assert "Write and review code" in result[role_extract.DUTIES]
    assert "3+ years" in result[role_extract.REQUIRED_QUALIFICATIONS]
    assert "Kubernetes" in result[role_extract.PREFERRED_QUALIFICATIONS]


# --- cache wrapper (overrides.db) -----------------------------------------------

@pytest.fixture()
def ov_conn(tmp_path):
    conn = ov.get_conn(tmp_path / ".jobtracker" / "overrides.db")
    yield conn
    conn.close()


def test_get_or_extract_populates_and_reuses_cache(tmp_path, ov_conn):
    apps = tmp_path / "Applications" / "Acme"
    apps.mkdir(parents=True)
    dest = apps / "job_posting.pdf"
    shutil.copy(FIXTURES / "sample_job_posting.pdf", dest)

    result1 = extract.get_or_extract(
        ov_conn, tmp_path, "Applications/Acme/job_posting.pdf", content_hash="abc123"
    )
    assert result1["extraction_ok"] is True

    cached_row = ov.get_extraction(ov_conn, "abc123")
    assert cached_row is not None
    assert cached_row["extractor_version"] == extract.EXTRACTOR_VERSION

    # Delete the underlying file -- a genuine re-extraction would now fail.
    # A correct cache hit never touches the filesystem, so this must still
    # succeed and return the same result.
    dest.unlink()
    result2 = extract.get_or_extract(
        ov_conn, tmp_path, "Applications/Acme/job_posting.pdf", content_hash="abc123"
    )
    assert result2 == result1


def test_get_or_extract_without_content_hash_never_caches(tmp_path, ov_conn):
    apps = tmp_path / "Applications" / "Acme"
    apps.mkdir(parents=True)
    dest = apps / "job_posting.pdf"
    shutil.copy(FIXTURES / "sample_job_posting.pdf", dest)

    extract.get_or_extract(
        ov_conn, tmp_path, "Applications/Acme/job_posting.pdf", content_hash=None
    )
    # nothing should have been written to the cache table
    row = ov_conn.execute("SELECT COUNT(*) AS n FROM document_extractions").fetchone()
    assert row["n"] == 0


def test_get_or_extract_ignores_stale_extractor_version(tmp_path, ov_conn, monkeypatch):
    apps = tmp_path / "Applications" / "Acme"
    apps.mkdir(parents=True)
    dest = apps / "job_posting.pdf"
    shutil.copy(FIXTURES / "sample_job_posting.pdf", dest)

    ov.set_extraction(ov_conn, "abc123", "0-old-version", {"emails": ["stale@example.com"]})

    result = extract.get_or_extract(
        ov_conn, tmp_path, "Applications/Acme/job_posting.pdf", content_hash="abc123"
    )
    # Stale version must be treated as a miss, so we get the real
    # extraction back, not the stale cached value.
    assert result["emails"] == ["jane.recruiter@acme-corp.com"]


def test_get_or_extract_treats_pre_checkpoint2_cache_entries_as_stale(tmp_path, ov_conn):
    """A cache entry written by Checkpoint 1's extractor (version "1") has
    no role_summary/duties/etc keys at all. The version bump to "2" must
    cause get_or_extract to treat it as a miss and re-extract, not return
    a payload that's silently missing the new fields."""
    apps = tmp_path / "Applications" / "Acme"
    apps.mkdir(parents=True)
    dest = apps / "job_posting.pdf"
    shutil.copy(FIXTURES / "sample_job_posting.pdf", dest)

    ov.set_extraction(
        ov_conn,
        "abc123",
        "1",  # Checkpoint 1's EXTRACTOR_VERSION
        {
            "extraction_ok": True,
            "error": None,
            "text_length": 42,
            "emails": ["jane.recruiter@acme-corp.com"],
            "phones": [],
            "urls": [],
            # deliberately no role_summary/duties/etc -- this is what a
            # real Checkpoint-1-era cached row looks like.
        },
    )

    result = extract.get_or_extract(
        ov_conn, tmp_path, "Applications/Acme/job_posting.pdf", content_hash="abc123"
    )
    for key in role_extract.SECTION_KEYS:
        assert key in result, f"{key} missing after cache-version bump"
        assert result[key] == role_extract.NOT_DETECTED


def test_get_or_extract_force_bypasses_cache(tmp_path, ov_conn):
    apps = tmp_path / "Applications" / "Acme"
    apps.mkdir(parents=True)
    dest = apps / "job_posting.pdf"
    shutil.copy(FIXTURES / "sample_job_posting.pdf", dest)

    ov.set_extraction(ov_conn, "abc123", extract.EXTRACTOR_VERSION, {"emails": ["cached@example.com"]})
    result = extract.get_or_extract(
        ov_conn, tmp_path, "Applications/Acme/job_posting.pdf", content_hash="abc123", force=True
    )
    assert result["emails"] == ["jane.recruiter@acme-corp.com"]
