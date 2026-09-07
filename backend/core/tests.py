"""
core app tests.

Phase 7 (docs/DJANGO_MIGRATION_PLAN.md): "Once the models above exist,
Django Admin gives you a working internal management interface ...
essentially for free -- worth wiring up before building any custom
internal tooling by hand." Every app already registered its models'
ModelAdmins incrementally as those models were created in Phases 1-4,
so there was no new registration work left to do here -- what this
test locks in is that the *whole* admin site actually renders for a
superuser, not just that admin.site.register() was called somewhere.
A model that fails to render (e.g. a bad list_display field, a
misconfigured autocomplete_fields) would otherwise only surface the
first time someone clicks into it by hand.
"""
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase


class AdminSiteSmokeTests(TestCase):
    """Covers every model registered with admin.site, across every
    installed app -- not a fixed list, so a newly-registered model in
    a later phase is covered automatically without editing this test.
    """

    @classmethod
    def setUpTestData(cls):
        cls.superuser = get_user_model().objects.create_superuser(
            username="admin-smoketest", email="admin@example.com", password="pw123456",
        )

    def setUp(self):
        self.client.force_login(self.superuser)

    def test_admin_index_loads(self):
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)

    def test_every_registered_model_changelist_loads(self):
        failures = []
        for model in admin.site._registry:
            app_label = model._meta.app_label
            model_name = model._meta.model_name
            url = f"/admin/{app_label}/{model_name}/"
            response = self.client.get(url)
            if response.status_code != 200:
                failures.append((url, response.status_code))
        self.assertEqual(failures, [], f"admin changelist(s) failed to load: {failures}")

    def test_every_registered_model_add_form_loads(self):
        # Catches autocomplete_fields/inline misconfiguration that only
        # trips on the add form, not the changelist (e.g. Phase 6's
        # JobPostingAdmin.autocomplete_fields = ("applied_application",)
        # depends on ApplicationAdmin defining search_fields).
        failures = []
        for model in admin.site._registry:
            app_label = model._meta.app_label
            model_name = model._meta.model_name
            url = f"/admin/{app_label}/{model_name}/add/"
            response = self.client.get(url)
            if response.status_code != 200:
                failures.append((url, response.status_code))
        self.assertEqual(failures, [], f"admin add form(s) failed to load: {failures}")
