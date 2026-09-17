"""Native identity, review/replay, archive, ownership and retired adapter contracts."""
from datetime import timedelta
import uuid

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient

from accounts.models import User, Workspace
from applications.models import Application
from core.models import ApplicationRequestIntent
from documents.models import Category, CategoryMembership, FolderOverride


class CategoryTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='categories', password='password')
        self.ws = Workspace.objects.create(owner=self.user, name='A')
        self.other = Workspace.objects.create(owner=self.user, name='B')
        self.foreign = Workspace.objects.create(owner=User.objects.create_user(username='foreign'), name='C')
        self.client.force_authenticate(self.user)

    def url(self, suffix='', workspace=None):
        return f'/api/workspaces/{(workspace or self.ws).pk}/categories/{suffix}'

    def send(self, body=None, key=None, pk=None, workspace=None):
        method = self.client.patch if pk else self.client.post
        return method(self.url(f'{pk}/' if pk else '', workspace), body or {'name': 'Research'},
                      format='json', HTTP_IDEMPOTENCY_KEY=key or uuid.uuid4().hex)

    def test_empty_categories_and_deterministic_order(self):
        rows = [self.send({'name': name, 'section': section}).data for name, section in
                [('z', 'misc'), ('B', 'credentials'), ('a', 'credentials'), ('x', 'network')]]
        same = Category.objects.create(workspace=self.ws, name='a', section='credentials')
        self.assertEqual([c['id'] for c in self.client.get(self.url()).data],
                         [rows[2]['id'], same.pk, rows[1]['id'], rows[3]['id'], rows[0]['id']])
        self.assertFalse(Application.objects.exists())
        self.assertFalse(CategoryMembership.objects.exists())
        self.assertEqual(self.client.get(self.url(f'{same.pk}/applications/')).data, [])

    def test_name_validation_and_display_spelling(self):
        for name in ['', '   ', 'Applications', ' APPLICATIONS ', 'Ａｐｐｌｉｃａｔｉｏｎｓ', 'a\nb', 'a\x00b', 'a\x7fb']:
            with self.subTest(name=name):
                self.assertEqual(self.send({'name': name}).status_code, 400)
        self.assertEqual(self.send({'name': '  Résumé / ideas  '}).data['name'], '  Résumé / ideas  ')
        self.assertEqual(self.send({'name': 'Valid', 'section': 'applications'}).status_code, 400)
        self.assertEqual(self.send({'name': 'Valid', 'challenge': 'é'}).status_code, 400)

    def test_create_replay_changed_intent_and_shared_namespace(self):
        key = uuid.uuid4().hex
        first = self.send(key=key)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(self.send(key=key).data, first.data)
        self.assertEqual(self.send({'name': 'Changed'}, key).data['code'], 'idempotency_key_reused')
        response = self.client.post(f'/api/workspaces/{self.ws.pk}/applications/', {'company': 'New'},
                                   format='json', HTTP_IDEMPOTENCY_KEY=key)
        self.assertEqual(response.data['code'], 'idempotency_key_reused')
        key2 = uuid.uuid4().hex
        self.client.post(f'/api/workspaces/{self.ws.pk}/applications/', {'company': 'New'},
                         format='json', HTTP_IDEMPOTENCY_KEY=key2)
        self.assertEqual(self.send(key=key2).data['code'], 'idempotency_key_reused')
        self.assertEqual(Category.objects.count(), 1)

    def test_duplicate_name_explicit_continuation_and_terminal_replay(self):
        original = self.send({'name': 'Research', 'section': 'network'}).data
        body = {'name': ' research ', 'section': 'misc'}
        key = uuid.uuid4().hex
        warning = self.send(body, key)
        self.assertEqual(warning.data['code'], 'duplicate_category_name')
        self.assertEqual(warning.data['candidates'][0]['id'], original['id'])
        continued = {**body, 'challenge': warning.data['challenge']}
        created = self.send(continued, key)
        self.assertEqual(created.status_code, 201, created.data)
        self.assertNotEqual(created.data['portable_id'], original['portable_id'])
        self.assertEqual(self.send(continued, key).data, created.data)
        Category.objects.get(pk=created.data['id']).delete()
        self.assertEqual(self.send(continued, key).data, {'state': 'removed', 'portable_id': created.data['portable_id']})
        self.assertEqual(Category.objects.count(), 1)

    def test_challenges_are_scoped_expiring_and_revision_bound(self):
        first = self.send().data
        key = uuid.uuid4().hex
        warning = self.send(key=key).data
        body = {'name': 'Research', 'challenge': warning['challenge']}
        self.assertEqual(self.send(body).data['code'], 'invalid_challenge')
        self.assertEqual(self.send(body, key, workspace=self.other).data['code'], 'invalid_challenge')
        self.assertEqual(self.send(body, key, workspace=self.foreign).status_code, 404)
        ApplicationRequestIntent.objects.filter(workspace=self.ws, key=key).update(challenge_expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.send(body, key).data['code'], 'challenge_expired')
        fresh = self.send(key=key).data['challenge']
        self.assertNotEqual(fresh, warning['challenge'])
        self.assertEqual(self.send(body, key).data['code'], 'invalid_challenge')
        self.send({'archived': True, 'expected_revision': 0}, pk=first['id'])
        self.assertEqual(self.send({'name': 'Research', 'challenge': fresh}, key).data['code'], 'stale_challenge')
        renewed = self.send(key=key).data['challenge']
        self.assertEqual(self.send({'name': 'Research', 'challenge': renewed}, key).status_code, 201)

    def test_metadata_revision_rename_collision_and_archive(self):
        first = self.send({'name': 'One'}).data
        second = self.send({'name': 'Two'}).data
        body = {'name': 'One', 'section': 'network', 'expected_revision': 0}
        key = uuid.uuid4().hex
        warning = self.send(body, key, second['id'])
        self.assertEqual(warning.data['code'], 'duplicate_category_name')
        changed = self.send({**body, 'challenge': warning.data['challenge']}, key, second['id'])
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.data['portable_id'], second['portable_id'])
        self.assertEqual(changed.data['revision'], 1)
        self.assertEqual(self.send({'archived': True, 'expected_revision': 0}, pk=second['id']).data['code'], 'stale_revision')
        archived = self.send({'archived': True, 'expected_revision': 1}, pk=second['id'])
        self.assertEqual(archived.data['revision'], 2)
        self.assertEqual(self.send({'archived': True, 'expected_revision': 2}, pk=second['id']).data['revision'], 2)
        self.assertEqual([c['id'] for c in self.client.get(self.url()).data], [first['id']])
        self.assertEqual(len(self.client.get(self.url(), {'show_archived': 'true'}).data), 2)
        self.assertTrue(self.client.get(self.url(f"{second['id']}/")).data['archived'])

    def test_ownership_immutable_identity_and_no_alternate_admin_writes(self):
        category = Category.objects.create(workspace=self.ws, name='Normal', section='misc')
        self.assertEqual(self.client.get(self.url(f'{category.pk}/', self.other)).status_code, 404)
        self.assertEqual(self.client.get(self.url(workspace=self.foreign)).status_code, 404)
        for field, value in [('workspace', self.other.pk), ('portable_id', str(uuid.uuid4())), ('revision', 7), ('provenance', {})]:
            self.assertEqual(self.send({'name': 'Valid', field: value}).status_code, 400)
        for field, value in [('workspace_id', self.other.pk), ('portable_id', uuid.uuid4())]:
            original = getattr(category, field)
            setattr(category, field, value)
            with self.assertRaises(ValidationError):
                category.save()
            setattr(category, field, original)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Category.objects.create(workspace=self.ws, portable_id=category.portable_id, name='Other', section='misc')
        Category.objects.create(workspace=self.other, portable_id=category.portable_id, name='Other', section='misc')
        self.user.is_staff = self.user.is_superuser = True
        self.user.save()
        self.client.force_login(self.user)
        for model in (Category, CategoryMembership, FolderOverride):
            authority = admin.site._registry[model]
            self.assertFalse(authority.has_add_permission(None))
            self.assertFalse(authority.has_change_permission(None, category))
            self.assertFalse(authority.has_delete_permission(None, category))
            self.assertEqual(self.client.post(f'/admin/documents/{model._meta.model_name}/add/', {}).status_code, 403)
        self.assertEqual(self.client.post(f'/admin/documents/category/{category.pk}/change/', {'name': 'Bypass'}).status_code, 403)
        category.refresh_from_db()
        self.assertEqual(category.name, 'Normal')

    def test_auth_csrf_and_retired_destructive_paths(self):
        self.assertEqual(APIClient().get(self.url()).status_code, 401)
        csrf = APIClient(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        self.assertEqual(csrf.post(self.url(), {'name': 'No CSRF'}).status_code, 403)
        app = Application.objects.create(workspace=self.ws, company='A', section='credentials')
        override = FolderOverride.objects.create(workspace=self.ws, folder='credentials', section='credentials', archived=True)
        for path in ['/api/categories/credentials/delete', '/api/categories/credentials/delete/',
                     self.url('credentials/override/'), self.url('credentials/delete/')]:
            self.assertEqual(self.client.post(path, {'workspace': self.ws.pk}).status_code, 404)
        category = self.send().data
        self.assertEqual(self.client.delete(self.url(f"{category['id']}/")).status_code, 405)
        self.assertTrue(Application.objects.filter(pk=app.pk).exists())
        self.assertTrue(FolderOverride.objects.filter(pk=override.pk).exists())


from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import close_old_connections, connection
from django.test import TransactionTestCase


class CategoryConcurrencyTests(TransactionTestCase):
    def test_simultaneous_create_reconciles_to_one_effect(self):
        user = User.objects.create_user(username='category_concurrency')
        workspace = Workspace.objects.create(owner=user, name='Concurrent')
        key = uuid.uuid4().hex
        url = f'/api/workspaces/{workspace.pk}/categories/'
        barrier = Barrier(2)
        def send(_):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(user)
                barrier.wait(timeout=10)
                return client.post(url, {'name': 'Same'}, format='json', HTTP_IDEMPOTENCY_KEY=key).status_code
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(send, range(2)))
        self.assertLessEqual(outcomes.count(201), 1, outcomes)
        self.assertTrue(set(outcomes) <= ({200, 201, 503} if connection.vendor == 'sqlite' else {200, 201}), outcomes)
        self.assertEqual(Category.objects.count(), outcomes.count(201))
        client = APIClient()
        client.force_authenticate(user)
        replay = client.post(url, {'name': 'Same'}, format='json', HTTP_IDEMPOTENCY_KEY=key)
        self.assertEqual(replay.status_code, 200 if 201 in outcomes else 201)
        self.assertEqual(Category.objects.count(), 1)
        self.assertEqual(ApplicationRequestIntent.objects.count(), 1)

    def test_simultaneous_membership_changes_cannot_both_use_one_revision(self):
        user = User.objects.create_user(username='member_concurrency')
        workspace = Workspace.objects.create(owner=user, name='Concurrent')
        app = Application.objects.create(workspace=workspace, company='Same', section='applications')
        cats = [Category.objects.create(workspace=workspace, name=str(i), section='misc') for i in range(2)]
        url = f'/api/workspaces/{workspace.pk}/applications/{app.pk}/category/'
        barrier = Barrier(2)
        def send(i):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(user)
                barrier.wait(timeout=10)
                return client.put(url, {'category_id': cats[i].pk, 'expected_revision': 0}, format='json').status_code
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(send, range(2)))
        self.assertLessEqual(outcomes.count(200), 1, outcomes)
        self.assertTrue(set(outcomes) <= ({200, 409, 503} if connection.vendor == 'sqlite' else {200, 409}), outcomes)
        app.refresh_from_db()
        self.assertEqual(app.category_revision, outcomes.count(200))
        client = APIClient()
        client.force_authenticate(user)
        if 200 not in outcomes:
            self.assertEqual(client.put(url, {'category_id': cats[0].pk, 'expected_revision': 0}, format='json').status_code, 200)
        self.assertEqual(client.put(url, {'category_id': None, 'expected_revision': 0}, format='json').status_code, 409)
        self.assertEqual(CategoryMembership.objects.count(), 1)
