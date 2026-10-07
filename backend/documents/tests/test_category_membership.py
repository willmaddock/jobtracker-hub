"""Organization must never change application business state or allocation identity."""
import uuid
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APITestCase
from accounts.models import User, Workspace
from applications.models import Application, Override, StatusHistory
from core.models import ApplicationRequestIntent
from documents.category_services import assign_category
from documents.models import Category, CategoryMembership, Document, FolderOverride
from email_sync.models import EmailAccount
from postings.models import JobPosting, PostingApplicationConversion


class MembershipTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='membership')
        self.ws = Workspace.objects.create(owner=self.user, name='A')
        self.other = Workspace.objects.create(owner=self.user, name='B')
        self.client.force_authenticate(self.user)
        self.one = Category.objects.create(workspace=self.ws, name='One', section='network')
        self.two = Category.objects.create(workspace=self.ws, name='Two', section='misc', archived=True)
        self.foreign = Category.objects.create(workspace=self.other, name='Foreign', section='misc')
        self.app = Application.objects.create(workspace=self.ws, section='applications', company='Acme', role_label='Engineer', status='interview')
        self.override = Override.objects.create(application=self.app, notes='Keep', manual_status='applied')
        self.history = StatusHistory.objects.create(application=self.app, status='applied', changed_at=timezone.now())
        self.doc = Document.objects.create(workspace=self.ws, application=self.app, file='fixture/no-write', filename='resume.pdf', ext='.pdf', size=1, content_hash='fixture')

    def url(self, suffix):
        return f'/api/workspaces/{self.ws.pk}/{suffix}'

    def move(self, category, revision, app=None):
        return self.client.put(self.url(f'applications/{(app or self.app).pk}/category/'),
            {'category_id': category.pk if category else None, 'expected_revision': revision}, format='json')

    def snapshot(self):
        app = Application.objects.values().get(pk=self.app.pk)
        app.pop('category_revision')
        return (app, list(Override.objects.values()), list(StatusHistory.objects.values()), list(Document.objects.values()))

    def test_assign_reassign_clear_and_revision_through_uncategorized(self):
        before = self.snapshot()
        self.assertEqual(self.move(None, 0).data['category_revision'], 0)
        self.assertEqual(self.move(self.one, 0).data['category_revision'], 1)
        self.assertEqual(self.move(self.one, 1).data['category_revision'], 1)
        self.assertEqual(self.move(self.two, 0).data['code'], 'stale_revision')
        self.assertEqual(self.move(self.two, 1).data['category_revision'], 2)
        self.assertEqual(CategoryMembership.objects.get(application=self.app).category_id, self.two.pk)
        self.assertEqual(self.move(None, 2).data['category_revision'], 3)
        self.assertFalse(CategoryMembership.objects.exists())
        self.assertEqual(self.move(self.one, 0).data['code'], 'stale_revision')
        self.assertEqual(self.snapshot(), before)
        row = self.client.get(self.url('applications/')).data[0]
        self.assertIsNone(row['category_id'])
        self.assertEqual(row['category_revision'], 3)

    def test_cross_workspace_api_service_and_model_saves(self):
        self.assertEqual(self.move(self.foreign, 0).status_code, 404)
        from rest_framework.exceptions import NotFound
        with self.assertRaises(NotFound):
            assign_category(actor=self.user, workspace=self.ws, application_id=self.app.pk,
                            category_id=self.foreign.pk, expected_revision=0)
        with self.assertRaises(ValidationError):
            CategoryMembership.objects.create(application=self.app, category=self.foreign)
        self.move(self.one, 0)
        member = CategoryMembership.objects.get(application=self.app)
        member.category = self.foreign
        with self.assertRaises(ValidationError):
            member.save()
        member.refresh_from_db()
        self.assertEqual(member.category_id, self.one.pk)
        outside = Application.objects.create(workspace=self.other, company='Outside', section='misc')
        self.assertEqual(self.move(self.one, 0, outside).status_code, 404)
        self.assertEqual(self.client.get(self.url(f'categories/{self.foreign.pk}/applications/')).status_code, 404)

    def test_archive_and_metadata_never_hide_system_members_or_change_business_state(self):
        self.move(self.one, 0)
        before = self.snapshot()
        response = self.client.patch(self.url(f'categories/{self.one.pk}/'),
            {'name': 'Renamed', 'section': 'credentials', 'archived': True, 'expected_revision': 0},
            format='json', HTTP_IDEMPOTENCY_KEY=uuid.uuid4().hex)
        self.assertEqual(response.status_code, 200)
        FolderOverride.objects.create(workspace=self.ws, folder='applications', archived=True)
        self.assertEqual(self.client.get(self.url(f'categories/{self.one.pk}/applications/')).data, [])
        shown = self.client.get(self.url(f'categories/{self.one.pk}/applications/'), {'show_archived': 'true'})
        self.assertEqual([row['id'] for row in shown.data], [self.app.pk])
        self.assertEqual(self.client.get(self.url('applications/')).data[0]['category_id'], self.one.pk)
        self.assertEqual(self.client.get(self.url('browse/')).data['applications'][0]['id'], self.app.pk)
        self.assertEqual(self.client.get(self.url('search/'), {'q': 'resume'}).data[0]['id'], self.doc.pk)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.move(self.two, 1).status_code, 200)
        # Even direct database deletion removes a link, never its Application/files.
        self.two.delete()
        self.assertFalse(CategoryMembership.objects.exists())
        self.assertEqual(self.snapshot(), before)

    def test_member_archive_is_independent_of_category_archive(self):
        self.move(self.one, 0)
        self.override.archived = True
        self.override.save()
        path = self.url(f'categories/{self.one.pk}/applications/')
        self.assertEqual(self.client.get(path).data, [])
        self.assertEqual([row['id'] for row in self.client.get(path, {'show_archived': 'true'}).data], [self.app.pk])
        self.one.refresh_from_db()
        self.assertFalse(self.one.archived)
        self.assertEqual(self.move(self.two, 1).status_code, 200)

    def test_repeated_applications_and_alias_changes_keep_independent_membership(self):
        repeat = Application.objects.create(workspace=self.ws, section='applications', company='Acme', role_label='Engineer')
        self.move(self.one, 0)
        self.move(self.two, 0, repeat)
        links = list(CategoryMembership.objects.order_by('application_id').values_list('application_id', 'category_id'))
        self.assertEqual(self.client.post(self.url('manage/merge/'), {'names': ['Acme', 'Alias'], 'canonical': 'Acme'}, format='json').status_code, 200)
        self.assertEqual(self.client.post(self.url('manage/unmerge/'), {'alias': 'Alias'}, format='json').status_code, 200)
        self.assertEqual(list(CategoryMembership.objects.order_by('application_id').values_list('application_id', 'category_id')), links)
        self.move(None, 1, repeat)
        self.assertEqual(CategoryMembership.objects.get().application_id, self.app.pk)


class CreationMembershipTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='creation_categories')
        self.ws = Workspace.objects.create(owner=self.user, name='A')
        self.other = Workspace.objects.create(owner=self.user, name='B')
        self.client.force_authenticate(self.user)
        self.category = Category.objects.create(workspace=self.ws, name='Library', section='credentials')
        self.foreign = Category.objects.create(workspace=self.other, name='Other', section='misc')
        account = EmailAccount.objects.create(workspace=self.ws, email='fixture@example.test')
        self.posting = JobPosting.objects.create(workspace=self.ws, account=account, company='Acme', title='Engineer', dedupe_key='fixture')

    def send(self, posting, body, key):
        suffix = f'job-postings/{self.posting.pk}/apply/' if posting else 'applications/'
        return self.client.post(f'/api/workspaces/{self.ws.pk}/{suffix}', body, format='json', HTTP_IDEMPOTENCY_KEY=key)

    def body(self, posting, **extra):
        return {**({} if posting else {'company': 'Manual'}), **extra}

    def test_both_paths_atomic_membership_and_replay_does_not_restore_moved_link(self):
        for posting in (False, True):
            key = uuid.uuid4().hex
            body = self.body(posting, category_id=self.category.pk)
            first = self.send(posting, body, key)
            self.assertEqual(first.status_code, 201, first.data)
            app = Application.objects.get(pk=first.data['application_id' if posting else 'id'])
            self.assertEqual((app.section, app.category_revision), ('applications', 1))
            self.assertEqual(app.category_membership.category_id, self.category.pk)
            self.assertEqual(self.send(posting, body, key).data, first.data)
            self.assertEqual(self.send(posting, {**body, 'category_id': None}, key).data['code'], 'idempotency_key_reused')
            assign_category(actor=self.user, workspace=self.ws, application_id=app.pk, category_id=None, expected_revision=1)
            replay = self.send(posting, body, key)
            self.assertEqual(replay.status_code, 200)
            app.refresh_from_db()
            self.assertFalse(CategoryMembership.objects.filter(application=app).exists())
            self.assertEqual(app.category_revision, 2)
            if not posting:
                self.assertIsNone(replay.data['category_id'])
                self.assertEqual(replay.data['category_revision'], 2)
        self.assertEqual(Application.objects.count(), 2)
        self.assertEqual(PostingApplicationConversion.objects.count(), 1)
        self.assertFalse(CategoryMembership.objects.exists())

    def test_omitted_null_invalid_and_cross_workspace(self):
        for posting in (False, True):
            for value in ('omit', None):
                key = uuid.uuid4().hex
                body = self.body(posting, **({} if value == 'omit' else {'category_id': value}))
                response = self.send(posting, body, key)
                if response.status_code == 409:
                    response = self.send(posting, {**body, 'challenge': response.data['challenge']}, key)
                self.assertEqual(response.status_code, 201, response.data)
                app = Application.objects.get(pk=response.data['application_id' if posting else 'id'])
                self.assertFalse(CategoryMembership.objects.filter(application=app).exists())
                self.assertEqual(app.category_revision, 0)
            for value, expected in [(self.foreign.pk, 404), (999999, 404), (-1, 400)]:
                self.assertEqual(self.send(posting, self.body(posting, category_id=value), uuid.uuid4().hex).status_code, expected)
        self.assertFalse(CategoryMembership.objects.exists())

    def test_category_changes_invalidate_pending_application_challenge(self):
        for posting in (False, True):
            body = self.body(posting, category_id=self.category.pk)
            first = self.send(posting, body, uuid.uuid4().hex)
            self.assertEqual(first.status_code, 201, first.data)
            key = uuid.uuid4().hex
            warning = self.send(posting, body, key)
            self.assertEqual(warning.status_code, 409)
            self.category.revision += 1
            self.category.archived = True
            self.category.save()
            self.assertEqual(self.send(posting, {**body, 'challenge': warning.data['challenge']}, key).data['code'], 'stale_challenge')
            renewed = self.send(posting, body, key)
            repeat = self.send(posting, {**body, 'challenge': renewed.data['challenge']}, key)
            self.assertEqual(repeat.status_code, 201, repeat.data)
        self.assertEqual(CategoryMembership.objects.count(), 4)

    def test_failed_initial_related_write_rolls_back_application_membership_and_intent(self):
        for posting in (False, True):
            with patch('applications.creation.StatusHistory.objects.create', side_effect=RuntimeError('fixture failure')):
                with self.assertRaises(RuntimeError):
                    self.send(posting, self.body(posting, category_id=self.category.pk, status='applied'), uuid.uuid4().hex)
            for model in (Application, CategoryMembership, Override, StatusHistory, ApplicationRequestIntent, PostingApplicationConversion):
                self.assertFalse(model.objects.exists(), model.__name__)


class CategoryReadContractTests(APITestCase):
    """Browser reads retain server membership and never cause product effects."""
    def setUp(self):
        self.user = User.objects.create_user(username="category_reader")
        self.ws = Workspace.objects.create(owner=self.user, name="Read A")
        self.other = Workspace.objects.create(owner=self.user, name="Read B")
        self.foreign = Workspace.objects.create(owner=User.objects.create_user(username="outside_reader"), name="Foreign")
        self.client.force_authenticate(self.user)
        self.category = Category.objects.create(workspace=self.ws, name="Same", section="network", archived=True)
        self.empty = Category.objects.create(workspace=self.ws, name="Same", section="misc")
        self.app = Application.objects.create(workspace=self.ws, company="Member", role_label="Role", section="applications")
        self.archived = Application.objects.create(workspace=self.ws, company="Archived", section="credentials")
        self.trashed = Application.objects.create(workspace=self.ws, company="Trash", trashed_at=timezone.now())
        Override.objects.create(application=self.archived, archived=True)
        for app in (self.app, self.archived, self.trashed):
            CategoryMembership.objects.create(application=app, category=self.category)

    def url(self, suffix="", workspace=None):
        return f"/api/workspaces/{(workspace or self.ws).pk}/categories/{suffix}"

    def test_archive_empty_order_identity_and_current_member_contract(self):
        self.assertEqual([r["id"] for r in self.client.get(self.url()).data], [self.empty.pk])
        listed = self.client.get(self.url(), {"show_archived": "true"}).data
        self.assertEqual([r["id"] for r in listed], [self.category.pk, self.empty.pk])
        self.assertEqual([r["name"] for r in listed], ["Same", "Same"])
        detail = self.client.get(self.url(f"{self.category.pk}/")).data
        self.assertEqual(detail["portable_id"], str(self.category.portable_id))
        self.assertEqual(detail["workspace"], self.ws.pk)
        self.assertTrue(detail["archived"])
        self.assertEqual(self.client.get(self.url(f"{self.category.pk}/applications/")).data, [])
        rows = self.client.get(self.url(f"{self.category.pk}/applications/"), {"show_archived": "true"}).data
        self.assertEqual([r["id"] for r in rows], [self.app.pk, self.archived.pk])
        self.assertEqual(rows[0]["section"], "applications")
        self.assertEqual(detail["section"], "network")
        self.assertEqual(rows[0]["category_id"], self.category.pk)
        self.assertEqual(rows[0]["portable_id"], str(self.app.portable_id))
        self.assertTrue(rows[1]["override"]["archived"])
        self.assertEqual(self.client.get(self.url(f"{self.empty.pk}/applications/"), {"show_archived": "true"}).data, [])
        self.category.archived = False
        self.category.save(update_fields=["archived"])
        self.assertEqual([r["id"] for r in self.client.get(self.url(f"{self.category.pk}/applications/")).data], [self.app.pk])

    def test_trashed_category_detail_is_readable_but_members_are_unavailable(self):
        self.category.trashed_at = timezone.now()
        self.category.save(update_fields=["trashed_at"])
        self.assertEqual([r["id"] for r in self.client.get(self.url(), {"show_archived": "true"}).data], [self.empty.pk])
        detail = self.client.get(self.url(f"{self.category.pk}/"))
        self.assertEqual(detail.status_code, 200)
        self.assertTrue(detail.data["is_trashed"])
        result = self.client.get(self.url(f"{self.category.pk}/applications/"), {"show_archived": "true"})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.data["code"], "resource_trashed")
        self.assertEqual(CategoryMembership.objects.filter(category=self.category).count(), 3)

    def test_auth_workspace_scope_and_privileged_malformed_foreign_membership(self):
        from rest_framework.test import APIClient
        suffixes = ("", f"{self.category.pk}/", f"{self.category.pk}/applications/")
        for suffix in suffixes:
            self.assertEqual(APIClient().get(self.url(suffix)).status_code, 401)
            self.assertEqual(self.client.get(self.url(suffix, self.foreign)).status_code, 404)
        for suffix in suffixes[1:]:
            self.assertEqual(self.client.get(self.url(suffix, self.other)).status_code, 404)
        self.assertEqual(self.client.get(self.url(workspace=self.other)).data, [])
        outside = Application.objects.create(workspace=self.other, company="Outside")
        # Privileged bypass exercises read containment; normal model saves prohibit this.
        CategoryMembership.objects.bulk_create([CategoryMembership(application=outside, category=self.category)])
        rows = self.client.get(self.url(f"{self.category.pk}/applications/"), {"show_archived": "true"}).data
        self.assertEqual([r["id"] for r in rows], [self.app.pk, self.archived.pk])
        self.assertTrue(all(r["workspace"] == self.ws.pk for r in rows))

    def test_complete_arrays_and_get_purity(self):
        from contextlib import ExitStack
        import re
        from django.apps import apps
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        for index in range(61):
            Category.objects.create(workspace=self.ws, name=f"Extra {index}", section="misc")
            app = Application.objects.create(workspace=self.ws, company=f"Extra {index}")
            CategoryMembership.objects.create(application=app, category=self.category)
        models = [model for model in apps.get_models() if model._meta.app_label in {"accounts", "applications", "documents", "email_sync", "postings", "core"}]
        def snapshot():
            return {model._meta.label: list(model.objects.order_by("pk").values()) for model in models}
        before = snapshot()
        with ExitStack() as blocked, CaptureQueriesContext(connection) as queries:
            for target in ("documents.category_views.mutate_category", "documents.category_views.assign_category", "applications.derivation.derive_application", "core.lifecycle.set_trash", "email_sync.tasks.sync_account_task.delay", "email_sync.tasks.sync_all_accounts_task.delay"):
                blocked.enter_context(patch(target, side_effect=AssertionError("GET caused an effect")))
            listed = self.client.get(self.url(), {"show_archived": "true"})
            detail = self.client.get(self.url(f"{self.category.pk}/"))
            members = self.client.get(self.url(f"{self.category.pk}/applications/"), {"show_archived": "true"})
        self.assertEqual([listed.status_code, detail.status_code, members.status_code], [200, 200, 200])
        self.assertEqual(len(listed.data), 63)
        self.assertEqual(len(members.data), 63)
        self.assertFalse(any(re.match(r"\s*(INSERT|UPDATE|DELETE|REPLACE|CREATE|ALTER|DROP)\b", item["sql"], re.I) for item in queries.captured_queries))
        self.assertEqual(snapshot(), before)
