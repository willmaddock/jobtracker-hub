from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User, Workspace
from applications.models import Application, Override


class PipelinePageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner", password="x")
        cls.other = User.objects.create_user("other", password="x")
        cls.ws = Workspace.objects.create(owner=cls.owner, name="working-db")
        cls.other_ws = Workspace.objects.create(owner=cls.other, name="private")
        Application.objects.create(workspace=cls.ws, section="applications", company="GCA USA",
                                   role_label="Junior Data Analyst", status="applied")
        Application.objects.create(workspace=cls.other_ws, section="applications", company="Secret Co",
                                   role_label="Spy", status="applied")

    def url(self, ws=None):
        return reverse("web:pipeline", args=[(ws or self.ws).pk])

    def test_anonymous_is_sent_to_sign_in(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/"))

    def test_owner_sees_own_applications_and_counts(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url())
        self.assertContains(response, "GCA USA")
        self.assertNotContains(response, "Secret Co")
        self.assertEqual(response.context["total"], 1)

    def test_manual_status_override_wins_in_counts_and_rows(self):
        app = Application.objects.get(company="GCA USA")
        Override.objects.create(application=app, manual_status="interviewing")
        self.client.force_login(self.owner)
        response = self.client.get(self.url())
        counts = {s["status"]: s["count"] for s in response.context["stats"]}
        self.assertEqual(counts["interviewing"], 1)
        self.assertEqual(counts["applied"], 0)
        self.assertContains(response, "Interviewing")

    def test_automatic_status_is_used_without_an_override(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url())
        counts = {s["status"]: s["count"] for s in response.context["stats"]}
        self.assertEqual(counts["applied"], 1)

    def test_other_users_workspace_is_404(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url(self.other_ws)).status_code, 404)

    def test_trashed_application_is_hidden(self):
        from django.utils import timezone
        Application.objects.filter(company="GCA USA").update(trashed_at=timezone.now())
        self.client.force_login(self.owner)
        self.assertNotContains(self.client.get(self.url()), "GCA USA")

    def test_home_redirects_to_first_workspace(self):
        self.client.force_login(self.owner)
        self.assertRedirects(self.client.get(reverse("web:home")), self.url())

    def test_home_without_workspace_shows_empty_state(self):
        user = User.objects.create_user("new", password="x")
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse("web:home")), "No tracker yet")

    def test_sign_out_requires_post_and_ends_session(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("web:sign-out")).status_code, 405)
        self.client.post(reverse("web:sign-out"))
        self.assertEqual(self.client.get(self.url()).status_code, 302)

    @override_settings(MFA_REQUIRED=True)
    def test_pages_are_blocked_until_mfa_is_verified(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/")


class PipelineViewAndActionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner2", password="x")
        cls.other = User.objects.create_user("other2", password="x")
        cls.ws = Workspace.objects.create(owner=cls.owner, name="working-db")
        cls.other_ws = Workspace.objects.create(owner=cls.other, name="private")
        cls.a = Application.objects.create(workspace=cls.ws, section="applications", company="GCA USA",
                                           role_label="Junior Data Analyst", status="applied")
        cls.b = Application.objects.create(workspace=cls.ws, section="applications", company="Summit Utilities",
                                           role_label="Data Engineer I", status="rejected")
        cls.foreign = Application.objects.create(workspace=cls.other_ws, section="applications",
                                                 company="Secret Co", role_label="Spy", status="applied")

    def url(self):
        return reverse("web:pipeline", args=[self.ws.pk])

    def act(self, app, action, data=None, ws=None):
        return self.client.post(
            reverse("web:application-action", args=[(ws or self.ws).pk, app.pk, action]), data or {})

    def test_list_view_shows_selected_detail(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url(), {"selected": self.b.pk})
        self.assertEqual(response.context["selected"]["id"], self.b.pk)
        self.assertContains(response, "Data Engineer I")

    def test_kanban_groups_cards_by_effective_status(self):
        Override.objects.create(application=self.a, manual_status="ghosted")
        self.client.force_login(self.owner)
        response = self.client.get(self.url(), {"view": "kanban"})
        cols = {c["status"]: [x["id"] for x in c["cards"]] for c in response.context["columns"]}
        self.assertEqual(cols["ghosted"], [self.a.pk])
        self.assertEqual(cols["rejected"], [self.b.pk])

    def test_status_filter_and_search(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url(), {"status": "rejected"})
        self.assertEqual([r["id"] for r in response.context["rows"]], [self.b.pk])
        response = self.client.get(self.url(), {"q": "gca"})
        self.assertEqual([r["id"] for r in response.context["rows"]], [self.a.pk])

    def test_set_status_writes_manual_status_and_can_reset(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.act(self.a, "status", {"status": "interviewing"}).status_code, 302)
        self.assertEqual(Override.objects.get(application=self.a).manual_status, "interviewing")
        self.act(self.a, "status", {"status": ""})
        self.assertIsNone(Override.objects.get(application=self.a).manual_status)

    def test_invalid_status_is_404(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.act(self.a, "status", {"status": "bogus"}).status_code, 404)

    def test_follow_up_and_reset_clock(self):
        self.client.force_login(self.owner)
        self.act(self.a, "follow-up")
        self.act(self.a, "reset-clock")
        o = Override.objects.get(application=self.a)
        self.assertEqual(o.next_action, "Follow up")
        self.assertIsNotNone(o.next_action_date)
        self.assertIsNotNone(o.activity_override)

    def test_actions_are_post_only_and_workspace_isolated(self):
        self.client.force_login(self.owner)
        url = reverse("web:application-action", args=[self.ws.pk, self.a.pk, "reset-clock"])
        self.assertEqual(self.client.get(url).status_code, 405)
        # another user's application, and another user's workspace, are both 404
        self.assertEqual(self.act(self.foreign, "reset-clock").status_code, 404)
        self.assertEqual(self.act(self.foreign, "reset-clock", ws=self.other_ws).status_code, 404)
        self.assertFalse(Override.objects.filter(application=self.foreign).exists())

    def test_next_redirect_cannot_leave_the_pipeline(self):
        self.client.force_login(self.owner)
        response = self.act(self.a, "reset-clock", {"next": "https://evil.example/"})
        self.assertEqual(response["Location"], self.url())
