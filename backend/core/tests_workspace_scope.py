"""Selected Workspace isolation, including same-owner boundaries."""
from rest_framework.test import APITestCase

from accounts.models import User, Workspace
from applications.models import Application, Override, StatusHistory
from documents.models import Document


class WorkspaceScopeTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="scope-u")
        other = User.objects.create_user(username="scope-v")
        self.a = Workspace.objects.create(owner=self.user, name="A")
        self.b = Workspace.objects.create(owner=self.user, name="B")
        self.c = Workspace.objects.create(owner=other, name="C")
        self.apps = [Application.objects.create(workspace=w, section="applications", company="Overlap", role_label="Role")
                     for w in (self.a, self.b, self.c)]
        self.client.force_authenticate(self.user)

    def url(self, suffix, workspace=None):
        return f"/api/workspaces/{(workspace or self.a).pk}/{suffix}"

    def test_list_and_metrics_are_selected_workspace_only(self):
        response = self.client.get(self.url("applications/"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r["id"] for r in response.data], [self.apps[0].pk])
        self.assertEqual(self.client.get(self.url("insights/")).data["total"], 1)

    def test_object_and_workspace_mismatches_have_no_effects(self):
        for app_id in (self.apps[1].pk, self.apps[2].pk, 999999):
            response = self.client.post(self.url(f"applications/{app_id}/override/"),
                                        {"notes": "changed"}, format="json")
            self.assertEqual(response.status_code, 404)
        self.assertFalse(Override.objects.exists())
        self.assertEqual(self.client.get(self.url("applications/", self.c)).status_code, 404)

    def test_bulk_prevalidates_before_any_effect(self):
        for foreign in (self.apps[1].pk, self.apps[2].pk, 999999):
            response = self.client.post(self.url("applications/bulk-override/"),
                {"item_ids": [self.apps[0].pk, foreign], "manual_status": "applied"}, format="json")
            self.assertEqual(response.status_code, 404)
            self.assertFalse(Override.objects.exists())
            self.assertFalse(StatusHistory.objects.exists())

    def test_creation_and_redundant_assignment(self):
        response = self.client.post(self.url("applications/"), {"company": "New"}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Application.objects.get(pk=response.data["id"]).workspace_id, self.a.pk)
        for field in ("workspace", "workspace_id", "owner", "owner_id"):
            response = self.client.post(self.url("applications/"),
                {"company": "Rejected", field: self.b.pk}, format="json")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(self.client.get(self.url("applications/"), {field: self.b.pk}).status_code, 400)
        self.assertFalse(Application.objects.filter(company="Rejected").exists())

    def test_inconsistent_document_is_not_disclosed_or_mutated(self):
        document = Document.objects.create(workspace=self.a, application=self.apps[1],
                                          filename="foreign.txt", file="foreign.txt", size=1)
        self.assertEqual(self.client.get(self.url(f"documents/{document.pk}/")).status_code, 404)
        self.assertEqual(self.client.post(self.url(f"documents/{document.pk}/rename/"),
            {"new_filename": "changed.txt"}, format="json").status_code, 404)
        document.refresh_from_db()
        self.assertEqual(document.filename, "foreign.txt")
        self.assertEqual(self.client.get(self.url("search/"), {"q": "foreign"}).data, [])

    def test_staff_does_not_broaden_scope(self):
        self.user.is_staff = self.user.is_superuser = True
        self.user.save()
        self.test_object_and_workspace_mismatches_have_no_effects()
        self.test_list_and_metrics_are_selected_workspace_only()

    def test_old_writes_removed_and_deletion_preserved(self):
        for path in ("/api/applications/", "/api/applications/bulk-override/",
                     "/api/manage/merge", "/api/hub/settings"):
            self.assertEqual(self.client.post(path, {}, format="json").status_code, 404)
        response = self.client.post(f"/api/applications/{self.apps[0].pk}/delete/")
        self.assertEqual(response.status_code, 200)

    def populate_related(self):
        from applications.models import CompanyAlias
        from email_sync.models import EmailAccount
        from postings.models import JobPosting
        from core.models import HubSettings
        self.docs, self.accounts, self.postings = [], [], []
        for workspace, app in zip((self.a, self.b, self.c), self.apps):
            self.docs.append(Document.objects.create(workspace=workspace, application=app,
                filename="overlap.txt", file="unused.txt", size=1, content_hash="same"))
            self.accounts.append(EmailAccount.objects.create(workspace=workspace, email="same@example.com"))
            self.postings.append(JobPosting.objects.create(workspace=workspace,
                account=self.accounts[-1], company="Overlap", title="Role", dedupe_key=str(workspace.pk)))
            CompanyAlias.objects.create(workspace=workspace, alias="Overlap", canonical=workspace.name)
            HubSettings.objects.create(workspace=workspace, role=workspace.name)

    def test_search_browse_manage_and_duplicate_counts(self):
        self.populate_related()
        response = self.client.get(self.url("search/"), {"q": "overlap"})
        self.assertEqual([r["id"] for r in response.data], [self.docs[0].pk])
        browse = self.client.get(self.url("browse/")).data
        self.assertEqual([r["id"] for r in browse["applications"]], [self.apps[0].pk])
        self.assertEqual(browse["applications"][0]["documents"][0]["duplicate_count"], 0)
        manage = self.client.get(self.url("manage/")).data
        self.assertEqual(manage["aliases"], {"Overlap": "A"})
        self.assertEqual(manage["duplicate_documents"], [])

    def test_settings_alias_and_category_mutations_stay_in_a(self):
        from core.models import HubSettings
        from applications.models import CompanyAlias
        from documents.models import FolderOverride
        self.populate_related()
        self.assertEqual(self.client.get(self.url("hub/settings/")).data["role"], "A")
        self.assertEqual(self.client.post(self.url("hub/settings/"), {"role": "Changed"}).status_code, 200)
        self.assertEqual(HubSettings.objects.get(workspace=self.b).role, "B")
        self.assertEqual(self.client.post(self.url("manage/merge/"),
            {"names": ["Overlap", "Canonical"], "canonical": "Canonical"}, format="json").status_code, 200)
        self.assertEqual(CompanyAlias.objects.get(workspace=self.b).canonical, "B")
        self.assertEqual(self.client.post(self.url("manage/unmerge/"), {"alias": "Overlap"}).status_code, 200)
        self.assertTrue(CompanyAlias.objects.filter(workspace=self.b).exists())
        for app in self.apps:
            app.section = "credentials"
            app.save()
        self.assertEqual(self.client.get(self.url("categories/")).data[0]["doc_count"], 1)
        self.assertEqual(self.client.post(self.url("categories/credentials/override/"),
            {"archived": True}, format="json").status_code, 200)
        self.assertEqual(list(FolderOverride.objects.values_list("workspace_id", flat=True)), [self.a.pk])

    def test_document_actions_and_nested_lists(self):
        self.populate_related()
        for i, doc in enumerate(self.docs):
            expected = 200 if i == 0 else 404
            for suffix, body in (("rename/", {"new_filename": "renamed.txt"}),
                                 ("override/", {"doc_type_override": "resume"})):
                self.assertEqual(self.client.post(self.url(f"documents/{doc.pk}/{suffix}"), body).status_code, expected)
            self.assertEqual(self.client.get(self.url(f"documents/{doc.pk}/")).status_code, expected)
            self.assertEqual(self.client.get(self.url(f"applications/{self.apps[i].pk}/documents/")).status_code, expected)
        # A parent must not serialize a B Document attached inconsistently to it.
        self.docs[1].application = self.apps[0]
        self.docs[1].save()
        response = self.client.get(self.url(f"applications/{self.apps[0].pk}/documents/"))
        self.assertEqual([r["id"] for r in response.data], [self.docs[0].pk])

    def test_posting_actions_and_inconsistent_references(self):
        self.populate_related()
        self.assertEqual([r["id"] for r in self.client.get(self.url("job-postings/")).data], [self.postings[0].pk])
        for job in self.postings[1:]:
            for action in ("save", "dismiss", "restore", "apply"):
                self.assertEqual(self.client.post(self.url(f"job-postings/{job.pk}/{action}/"),
                    {"saved": True}, format="json").status_code, 404)
        job = self.postings[0]
        job.applied_application = self.apps[1]
        job.save()
        self.assertEqual(self.client.get(self.url("job-postings/")).data, [])
        self.assertEqual(self.client.post(self.url(f"job-postings/{job.pk}/dismiss/")).status_code, 404)
        job.applied_application = None
        job.account = self.accounts[1]
        job.save()
        self.assertEqual(self.client.post(self.url(f"job-postings/{job.pk}/apply/")).status_code, 404)
        self.assertEqual(Application.objects.count(), 3)

    def test_upload_scope_and_foreign_parent_has_no_effects(self):
        import tempfile
        from django.test import override_settings
        from django.core.files.uploadedfile import SimpleUploadedFile
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            for app in self.apps[1:]:
                response = self.client.post(self.url(f"applications/{app.pk}/documents/"),
                    {"files": [SimpleUploadedFile("resume.txt", b"text")]}, format="multipart")
                self.assertEqual(response.status_code, 404)
            self.assertFalse(Document.objects.exists())
            response = self.client.post(self.url(f"applications/{self.apps[0].pk}/documents/"),
                {"files": [SimpleUploadedFile("resume.txt", b"text")]}, format="multipart")
            self.assertEqual(response.status_code, 201)
            document = Document.objects.get()
            self.assertEqual((document.workspace_id, document.application_id), (self.a.pk, self.apps[0].pk))

    def test_bulk_success(self):
        response = self.client.post(self.url("applications/bulk-override/"),
            {"item_ids": [self.apps[0].pk], "archived": True}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(Override.objects.values_list("application_id", flat=True)), [self.apps[0].pk])

    def test_attention_and_archive_filters_do_not_mix_workspaces(self):
        from datetime import timedelta
        from django.utils import timezone
        from documents.models import FolderOverride
        Application.objects.update(status="applied", last_activity=timezone.now() - timedelta(days=90))
        response = self.client.get(self.url("attention/"))
        self.assertEqual([r["id"] for r in response.data], [self.apps[0].pk])
        self.populate_related()
        Application.objects.update(section="credentials")
        FolderOverride.objects.create(workspace=self.b, folder="credentials", archived=True)
        self.assertEqual(len(self.client.get(self.url("search/"), {"q": "overlap"}).data), 1)
        self.assertEqual(len(self.client.get(self.url("browse/")).data["credentials"]), 1)
        self.assertFalse(self.client.get(self.url("categories/")).data[0]["archived"])

    def test_dossier_filters_nested_documents_and_account_matches(self):
        from unittest.mock import patch
        from email_sync.models import AccountMatch
        self.populate_related()
        for i, account in enumerate(self.accounts):
            AccountMatch.objects.create(account=account, application=self.apps[0], message_id=str(i))
        self.docs[1].application = self.apps[0]
        self.docs[1].save()
        with patch("applications.views.assemble_dossier", return_value={}) as assemble:
            response = self.client.get(self.url(f"applications/{self.apps[0].pk}/dossier/"))
            self.assertEqual(response.status_code, 200)
            self.assertEqual([d.pk for d in assemble.call_args.args[0]], [self.docs[0].pk])
            self.assertEqual([m["account_id"] for m in response.data["account_matches"]], [self.accounts[0].pk])
            assemble.reset_mock()
            for app in self.apps[1:]:
                self.assertEqual(self.client.get(self.url(f"applications/{app.pk}/dossier/")).status_code, 404)
            assemble.assert_not_called()

    def test_inconsistent_cache_provenance_blocks_dossier_before_effects(self):
        from unittest.mock import patch
        from django.utils import timezone
        from documents.models import DocumentExtraction
        self.populate_related()
        DocumentExtraction.objects.create(workspace=self.a, document=self.docs[1], content_hash="same",
            extracted_json={}, extractor_version="test", extracted_at=timezone.now())
        with patch("applications.views.assemble_dossier") as assemble:
            self.assertEqual(self.client.get(self.url(f"applications/{self.apps[0].pk}/dossier/")).status_code, 404)
            assemble.assert_not_called()
        self.assertFalse(Override.objects.exists())

    def test_inconsistent_documents_do_not_inflate_counts(self):
        self.populate_related()
        Document.objects.create(workspace=self.a, application=self.apps[1], filename="bad.txt",
                                file="unused.txt", content_hash="same", size=1)
        response = self.client.get(self.url(f"applications/{self.apps[0].pk}/documents/"))
        self.assertEqual(response.data[0]["duplicate_count"], 0)
        self.assertEqual(self.client.get(self.url("manage/")).data["duplicate_documents"], [])

    def test_missing_workspace_and_existing_auth_requirement(self):
        self.assertEqual(self.client.get("/api/workspaces/999999/search/").status_code, 404)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url("applications/")).status_code, 403)

    def test_no_alternative_scope_or_move_assignment(self):
        self.populate_related()
        session = self.client.session
        session["workspace_id"] = self.b.pk
        session.save()
        response = self.client.get(self.url("applications/"), HTTP_X_WORKSPACE_ID=str(self.b.pk))
        self.assertEqual([r["id"] for r in response.data], [self.apps[0].pk])
        for suffix, payload in (
            (f"applications/{self.apps[0].pk}/override/", {"notes": "bad"}),
            (f"documents/{self.docs[0].pk}/rename/", {"new_filename": "bad.txt"}),
            (f"job-postings/{self.postings[0].pk}/save/", {"saved": True}),
            ("hub/settings/", {"role": "bad"}),
        ):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.client.post(self.url(suffix),
                    {**payload, "workspace": self.a.pk}, format="json").status_code, 400)
                self.assertEqual(self.client.post(self.url(suffix) + f"?workspace={self.b.pk}",
                    payload, format="json").status_code, 400)
        self.assertFalse(Override.objects.exists())
        self.docs[0].refresh_from_db()
        self.assertEqual(self.docs[0].filename, "overlap.txt")

    def test_all_old_included_routes_are_unregistered(self):
        from django.urls import Resolver404, resolve
        old_paths = ["applications/", "applications/1/documents/", "applications/1/dossier/",
            "applications/1/override/", "applications/bulk-override/", "documents/1/",
            "documents/1/rename/", "documents/1/override/", "job-postings/",
            "attention", "insights", "search", "browse", "manage", "manage/merge",
            "manage/unmerge", "categories", "categories/credentials/override", "hub/settings"]
        old_paths += [f"job-postings/1/{action}/" for action in ("dismiss", "restore", "save", "apply")]
        for path in old_paths:
            with self.subTest(path=path), self.assertRaises(Resolver404):
                resolve("/api/" + path)
        for path in ("applications/1/delete/", "applications/bulk-delete/", "documents/1/delete/"):
            match = resolve("/api/" + path)
            self.assertTrue(match.func.cls.__name__.startswith("Legacy"))
            self.assertEqual(set(match.func.actions.values()) - {"delete", "bulk_delete"}, set())
        for suffix in ("applications/1/delete/", "applications/bulk-delete/", "documents/1/delete/",
                       "categories/credentials/delete/", "delete/", "trash/"):
            with self.subTest(suffix=suffix), self.assertRaises(Resolver404):
                resolve(self.url(suffix))

    def test_bulk_has_bounded_target_count(self):
        response = self.client.post(self.url("applications/bulk-override/"),
            {"item_ids": [self.apps[0].pk] * 1001, "archived": True}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Override.objects.exists())

    def test_format_suffix_routes_resolve_to_the_same_scoped_or_deletion_handler(self):
        from django.urls import resolve
        paths = [
            self.url("applications/"),
            self.url("applications/1/documents/"),
            self.url("applications/1/dossier/"),
            self.url("applications/1/override/"),
            self.url("applications/bulk-override/"),
            self.url("documents/1/"),
            self.url("documents/1/rename/"),
            self.url("documents/1/override/"),
            self.url("job-postings/"),
            "/api/applications/1/delete/",
            "/api/applications/bulk-delete/",
            "/api/documents/1/delete/",
        ]
        paths += [self.url(f"job-postings/1/{action}/")
                  for action in ("dismiss", "restore", "save", "apply")]
        for path in paths:
            plain = resolve(path)
            for suffix in (".json", ".json/", ".api", ".api/"):
                with self.subTest(path=path, suffix=suffix):
                    formatted = resolve(path.rstrip("/") + suffix)
                    self.assertIs(formatted.func.cls, plain.func.cls)
                    self.assertEqual(formatted.func.actions, plain.func.actions)
                    self.assertEqual(formatted.kwargs, {**plain.kwargs, "format": suffix.strip("./")})

    def test_json_suffix_requests_preserve_workspace_isolation(self):
        self.populate_related()
        response = self.client.get(self.url("applications.json"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.data], [self.apps[0].pk])
        for i, app in enumerate(self.apps):
            expected = 200 if i == 0 else 404
            self.assertEqual(self.client.get(self.url(f"applications/{app.pk}/documents.json/")).status_code, expected)
            self.assertEqual(self.client.get(self.url(f"documents/{self.docs[i].pk}.json")).status_code, expected)
            self.assertEqual(self.client.post(self.url(f"applications/{app.pk}/override.json"),
                {"notes": "A only"}, format="json").status_code, expected)
            self.assertEqual(self.client.post(self.url(f"job-postings/{self.postings[i].pk}/save.json/"),
                {"saved": True}, format="json").status_code, expected)
        self.assertEqual(list(Override.objects.values_list("application_id", flat=True)), [self.apps[0].pk])
        self.assertEqual(self.client.get(self.url("applications.json", self.c)).status_code, 404)

    def test_legacy_bulk_delete_accepts_format_without_changing_authorization(self):
        Override.objects.create(application=self.apps[0], archived=True)
        Override.objects.create(application=self.apps[2], archived=True)
        response = self.client.post("/api/applications/bulk-delete.json", {
            "item_ids": [self.apps[0].pk, self.apps[2].pk],
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Application.objects.filter(pk=self.apps[0].pk).exists())
        self.assertTrue(Application.objects.filter(pk=self.apps[2].pk).exists())

    def test_suffix_compatibility_does_not_restore_old_routes_or_expand_adapters(self):
        from django.urls import Resolver404, resolve
        paths = ["/api/applications/", "/api/applications/1/documents/",
            "/api/applications/1/dossier/", "/api/applications/1/override/",
            "/api/applications/bulk-override/", "/api/documents/1/",
            "/api/documents/1/rename/", "/api/documents/1/override/", "/api/job-postings/"]
        paths += [f"/api/job-postings/1/{action}/" for action in ("dismiss", "restore", "save", "apply")]
        paths += [self.url("categories/"), self.url("categories/credentials/override/"),
                  "/api/categories/credentials/delete", self.url("attention/"),
                  self.url("applications/1/delete/"), self.url("documents/1/delete/")]
        for path in paths:
            for suffix in (".json", ".json/"):
                with self.subTest(path=path, suffix=suffix), self.assertRaises(Resolver404):
                    resolve(path.rstrip("/") + suffix)
