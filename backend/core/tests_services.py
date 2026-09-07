"""
core services tests.

Phase 8 (docs/DJANGO_MIGRATION_PLAN.md) -- unit coverage for
core/services.py's pure enrichment/metrics/attention/duplicate logic,
kept separate from core/tests_cross_cutting.py's API-level tests the
same way applications/tests/test_services.py is kept separate from
applications/tests/test_views.py.
"""
from __future__ import annotations

import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Workspace
from applications.models import Application, CompanyAlias, Override
from documents.models import Document

from .services import (
    STALE_APPLIED_DAYS,
    STALE_DRAFTED_DAYS,
    annotate_application,
    compute_metrics,
    find_duplicate_groups,
    load_applications,
    needs_attention,
    normalize_company_key,
    suggest_duplicate_companies,
)


def _make_app(workspace, **kwargs):
    defaults = {
        "section": "applications",
        "company": "Acme",
        "role_label": "SWE",
        "source_relpath": "",
    }
    defaults.update(kwargs)
    return Application.objects.create(workspace=workspace, **defaults)


class AnnotateApplicationTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username="alice", password="pw123456")
        self.workspace = Workspace.objects.create(owner=user, name="Alice's workspace")

    def test_no_override_uses_auto_status(self):
        application = _make_app(self.workspace, status="applied")
        row = annotate_application(application)
        self.assertEqual(row["effective_status"], "applied")
        self.assertFalse(row["archived"])
        self.assertIsNone(row["days_since_activity"])

    def test_manual_status_overrides_auto_status(self):
        application = _make_app(self.workspace, status="applied")
        Override.objects.create(application=application, manual_status="interviewing")
        application.refresh_from_db()
        row = annotate_application(application)
        self.assertEqual(row["effective_status"], "interviewing")

    def test_stale_applied_flagged_after_threshold(self):
        stale_date = timezone.now() - timedelta(days=STALE_APPLIED_DAYS)
        application = _make_app(self.workspace, status="applied", last_activity=stale_date)
        row = annotate_application(application)
        self.assertTrue(row["is_stale"])

    def test_not_stale_below_threshold(self):
        recent = timezone.now() - timedelta(days=STALE_APPLIED_DAYS - 1)
        application = _make_app(self.workspace, status="applied", last_activity=recent)
        row = annotate_application(application)
        self.assertFalse(row["is_stale"])

    def test_drafted_uses_shorter_stale_threshold(self):
        stale_date = timezone.now() - timedelta(days=STALE_DRAFTED_DAYS)
        application = _make_app(self.workspace, status="drafted", last_activity=stale_date)
        row = annotate_application(application)
        self.assertTrue(row["is_stale"])

    def test_archived_is_never_stale(self):
        stale_date = timezone.now() - timedelta(days=STALE_APPLIED_DAYS)
        application = _make_app(self.workspace, status="applied", last_activity=stale_date)
        Override.objects.create(application=application, archived=True)
        application.refresh_from_db()
        row = annotate_application(application)
        self.assertFalse(row["is_stale"])
        self.assertTrue(row["archived"])

    def test_activity_override_wins_over_date_applied_and_last_activity(self):
        # activity_override resets the clock to "today" -- even though
        # last_activity/date_applied are both stale, this application
        # should NOT show up as stale.
        long_ago = (timezone.now() - timedelta(days=90)).date()
        application = _make_app(
            self.workspace, status="applied", last_activity=timezone.now() - timedelta(days=90)
        )
        Override.objects.create(
            application=application, date_applied=long_ago, activity_override=timezone.now().date()
        )
        application.refresh_from_db()
        row = annotate_application(application)
        self.assertEqual(row["days_since_activity"], 0)
        self.assertFalse(row["is_stale"])
        self.assertTrue(row["activity_is_reset"])

    def test_next_action_date_in_past_is_due(self):
        application = _make_app(self.workspace, status="applied")
        Override.objects.create(
            application=application, next_action_date=(timezone.now() - timedelta(days=1)).date()
        )
        application.refresh_from_db()
        row = annotate_application(application)
        self.assertTrue(row["next_action_due"])

    def test_next_action_date_in_future_is_not_due(self):
        application = _make_app(self.workspace, status="applied")
        Override.objects.create(
            application=application, next_action_date=(timezone.now() + timedelta(days=1)).date()
        )
        application.refresh_from_db()
        row = annotate_application(application)
        self.assertFalse(row["next_action_due"])

    def test_snoozed_until_future_is_snoozed(self):
        application = _make_app(self.workspace, status="applied")
        Override.objects.create(
            application=application, snoozed_until=(timezone.now() + timedelta(days=1)).date()
        )
        application.refresh_from_db()
        row = annotate_application(application)
        self.assertTrue(row["is_snoozed"])

    def test_snoozed_until_past_is_not_snoozed(self):
        application = _make_app(self.workspace, status="applied")
        Override.objects.create(
            application=application, snoozed_until=(timezone.now() - timedelta(days=1)).date()
        )
        application.refresh_from_db()
        row = annotate_application(application)
        self.assertFalse(row["is_snoozed"])


class LoadApplicationsTests(TestCase):
    def test_applies_company_alias(self):
        user = get_user_model().objects.create_user(username="alice", password="pw123456")
        workspace = Workspace.objects.create(owner=user, name="ws")
        _make_app(workspace, company="Bet365")
        CompanyAlias.objects.create(workspace=workspace, alias="Bet365", canonical="Bet365 Group")
        rows = load_applications(Application.objects.filter(workspace=workspace))
        self.assertEqual(rows[0]["effective_company"], "Bet365 Group")

    def test_alias_is_scoped_per_workspace(self):
        user = get_user_model().objects.create_user(username="alice", password="pw123456")
        ws1 = Workspace.objects.create(owner=user, name="ws1")
        ws2 = Workspace.objects.create(owner=user, name="ws2")
        _make_app(ws1, company="Acme")
        _make_app(ws2, company="Acme")
        CompanyAlias.objects.create(workspace=ws1, alias="Acme", canonical="Acme Corp")
        rows = load_applications(Application.objects.filter(workspace__owner=user).order_by("workspace_id"))
        by_workspace = {row["workspace_id"]: row["effective_company"] for row in rows}
        self.assertEqual(by_workspace[ws1.id], "Acme Corp")
        self.assertEqual(by_workspace[ws2.id], "Acme")


class ComputeMetricsTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username="alice", password="pw123456")
        self.workspace = Workspace.objects.create(owner=user, name="ws")

    def test_counts_by_effective_status_excluding_archived(self):
        a1 = _make_app(self.workspace, status="applied", company="A")
        a2 = _make_app(self.workspace, status="interviewing", company="B")
        a3 = _make_app(self.workspace, status="applied", company="C")
        Override.objects.create(application=a3, archived=True)
        for app in (a1, a2, a3):
            app.refresh_from_db()
        rows = load_applications(Application.objects.filter(workspace=self.workspace))
        metrics = compute_metrics(rows)
        self.assertEqual(metrics["total"], 2)
        self.assertEqual(metrics["by_status"]["applied"], 1)
        self.assertEqual(metrics["by_status"]["interviewing"], 1)

    def test_response_and_interview_rate(self):
        _make_app(self.workspace, status="applied", company="A")
        _make_app(self.workspace, status="interviewing", company="B")
        _make_app(self.workspace, status="rejected", company="C")
        rows = load_applications(Application.objects.filter(workspace=self.workspace))
        metrics = compute_metrics(rows)
        # sent = applied + interviewing + rejected = 3; responded = interviewing + rejected = 2
        self.assertAlmostEqual(metrics["response_rate"], 200 / 3)
        self.assertAlmostEqual(metrics["interview_rate"], 100 / 3)

    def test_no_sent_applications_gives_zero_rates(self):
        _make_app(self.workspace, status="drafted", company="A")
        rows = load_applications(Application.objects.filter(workspace=self.workspace))
        metrics = compute_metrics(rows)
        self.assertEqual(metrics["response_rate"], 0.0)
        self.assertEqual(metrics["interview_rate"], 0.0)
        self.assertIsNone(metrics["avg_response_days"])


class NeedsAttentionTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username="alice", password="pw123456")
        self.workspace = Workspace.objects.create(owner=user, name="ws")

    def test_next_action_due_sorted_before_stale_only(self):
        stale_only = _make_app(
            self.workspace, status="applied", company="Stale",
            last_activity=timezone.now() - timedelta(days=STALE_APPLIED_DAYS + 5),
        )
        due = _make_app(self.workspace, status="applied", company="Due")
        Override.objects.create(
            application=due, next_action_date=(timezone.now() - timedelta(days=1)).date()
        )
        for app in (stale_only, due):
            app.refresh_from_db()
        rows = load_applications(Application.objects.filter(workspace=self.workspace))
        attention = needs_attention(rows)
        self.assertEqual(attention[0]["company"], "Due")
        self.assertEqual({r["company"] for r in attention}, {"Stale", "Due"})

    def test_snoozed_is_excluded(self):
        application = _make_app(
            self.workspace, status="applied", company="Snoozed",
            last_activity=timezone.now() - timedelta(days=STALE_APPLIED_DAYS + 5),
        )
        Override.objects.create(
            application=application, snoozed_until=(timezone.now() + timedelta(days=1)).date()
        )
        application.refresh_from_db()
        rows = load_applications(Application.objects.filter(workspace=self.workspace))
        self.assertEqual(needs_attention(rows), [])

    def test_fresh_application_is_not_flagged(self):
        application = _make_app(self.workspace, status="applied", last_activity=timezone.now())
        rows = load_applications(Application.objects.filter(workspace=self.workspace))
        self.assertEqual(needs_attention(rows), [])


class NormalizeCompanyKeyTests(TestCase):
    def test_case_and_punctuation_insensitive(self):
        self.assertEqual(normalize_company_key("Bet365"), normalize_company_key("BET 365"))

    def test_drops_suffix_after_dash(self):
        self.assertEqual(normalize_company_key("Bet365 — ABET"), "bet365")


class SuggestDuplicateCompaniesTests(TestCase):
    def test_groups_names_with_same_loose_key(self):
        rows = [{"company": "Bet365"}, {"company": "BET 365"}, {"company": "Acme"}]
        suggestions = suggest_duplicate_companies(rows)
        self.assertIn("bet365", suggestions)
        self.assertEqual(set(suggestions["bet365"]), {"Bet365", "BET 365"})
        self.assertNotIn("acme", suggestions)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class FindDuplicateGroupsTests(TestCase):
    def test_groups_documents_sharing_a_content_hash(self):
        user = get_user_model().objects.create_user(username="alice", password="pw123456")
        workspace = Workspace.objects.create(owner=user, name="ws")
        app1 = _make_app(workspace, company="Acme", role_label="SWE")
        app2 = _make_app(workspace, company="Globex", role_label="PM")
        Document.objects.create(
            workspace=workspace, application=app1, file=SimpleUploadedFile("a.pdf", b"x"),
            filename="resume.pdf", doc_type="resume", ext=".pdf", content_hash="deadbeef", size=10,
        )
        Document.objects.create(
            workspace=workspace, application=app2, file=SimpleUploadedFile("b.pdf", b"x"),
            filename="resume-copy.pdf", doc_type="resume", ext=".pdf", content_hash="deadbeef", size=10,
        )
        Document.objects.create(
            workspace=workspace, application=app1, file=SimpleUploadedFile("c.pdf", b"x"),
            filename="cover.pdf", doc_type="cover_letter", ext=".pdf", content_hash="unique", size=5,
        )
        groups = find_duplicate_groups(Document.objects.filter(workspace=workspace))
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["content_hash"], "deadbeef")
        self.assertEqual(len(groups[0]["documents"]), 2)
