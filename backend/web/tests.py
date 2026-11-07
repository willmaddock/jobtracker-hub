from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User, Workspace
from applications.models import Application


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
