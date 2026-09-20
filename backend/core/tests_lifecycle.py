"""Retained lifecycle workflows, evidence eligibility, isolation and races."""
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.contrib import admin
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, connections
from django.db.models.deletion import ProtectedError
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from accounts.models import User, Workspace
from applications.models import Application, Override, StatusHistory
from documents.models import Category, CategoryMembership, Document, DocumentOverride, DocumentExtraction
from email_sync.models import EmailAccount
from postings.models import JobPosting
from core.lifecycle import set_trash


class LifecycleTests(APITestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        settings = override_settings(MEDIA_ROOT=temp.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.user = User.objects.create_user(username='lifecycle')
        self.ws = Workspace.objects.create(owner=self.user, name='A')
        self.other = Workspace.objects.create(owner=self.user, name='B')
        self.foreign = Workspace.objects.create(owner=User.objects.create_user(username='other'), name='C')
        self.client.force_authenticate(self.user)
        self.app = Application.objects.create(workspace=self.ws, company='Same', role_label='Role', section='applications',
                                              status='applied', last_activity=timezone.now(), first_activity=timezone.now())
        self.override = Override.objects.create(application=self.app, archived=True, manual_status='interviewing', notes='retain')
        StatusHistory.objects.create(application=self.app, status='interviewing', changed_at=timezone.now())
        self.cat = Category.objects.create(workspace=self.ws, name='Library', section='misc', archived=True)
        CategoryMembership.objects.create(application=self.app, category=self.cat)
        self.docs = [Document.objects.create(workspace=self.ws, application=self.app,
                    file=SimpleUploadedFile(f'evidence{i}.txt', b'original evidence'), filename=f'evidence{i}.txt',
                    ext='.txt', size=17, content_hash=f'hash{i}', doc_type='application_confirmation') for i in range(2)]
        DocumentOverride.objects.create(document=self.docs[1], doc_type_override='resume')
        DocumentExtraction.objects.create(workspace=self.ws, document=self.docs[0], content_hash='hash0',
                                         extractor_version='fixture', extracted_json={'retain': True}, extracted_at=timezone.now())

    def url(self, suffix, ws=None):
        return f'/api/workspaces/{(ws or self.ws).pk}/{suffix}'

    def transition(self, kind, obj, action, revision, ws=None):
        return self.client.post(self.url(f'{kind}/{obj.pk}/{action}/', ws), {'expected_revision': revision}, format='json')

    def snapshot(self):
        row = Application.objects.values().get(pk=self.app.pk)
        for field in ('trashed_at', 'lifecycle_revision'):
            row.pop(field)
        return (row, list(Override.objects.values()), list(StatusHistory.objects.values()),
                list(CategoryMembership.objects.values()), list(DocumentOverride.objects.values()),
                list(DocumentExtraction.objects.values()))

    def test_all_resources_revisions_noops_stale_and_validation(self):
        for kind, obj in [('applications', self.app), ('documents', self.docs[0]), ('categories', self.cat)]:
            with self.subTest(kind=kind):
                self.assertEqual(self.transition(kind, obj, 'restore', 0).data['lifecycle_revision'], 0)
                first = self.transition(kind, obj, 'trash', 0)
                self.assertEqual(first.status_code, 200, first.data)
                obj.refresh_from_db()
                stamp = obj.trashed_at
                self.assertIsNotNone(stamp)
                self.assertEqual(self.transition(kind, obj, 'trash', 1).data['lifecycle_revision'], 1)
                obj.refresh_from_db()
                self.assertEqual(obj.trashed_at, stamp)
                self.assertEqual(self.transition(kind, obj, 'restore', 0).data['code'], 'stale_revision')
                restored = self.transition(kind, obj, 'restore', 1)
                self.assertEqual(restored.data['lifecycle_revision'], 2)
                self.assertFalse(restored.data['effective_trashed'])
                self.assertEqual(self.transition(kind, obj, 'restore', 2).data['lifecycle_revision'], 2)
                for value in (None, -1, True, '2', 2.5):
                    self.assertEqual(self.transition(kind, obj, 'trash', value).status_code, 400)
                self.assertEqual(self.client.post(self.url(f'{kind}/{obj.pk}/trash/'),
                                 {'expected_revision': 2, 'archived': False}, format='json').status_code, 400)

    def test_parent_child_preservation_and_original_evidence_eligibility(self):
        from applications.derivation import derive_application
        derive_application(actor=self.user, workspace=self.ws, application_id=self.app.pk)
        before = self.snapshot()
        files = [(d.pk, d.file.name, d.file.read()) for d in self.docs]
        self.transition('documents', self.docs[1], 'trash', 0)
        self.transition('applications', self.app, 'trash', 0)
        self.assertEqual(Document.objects.live().count(), 0)
        self.docs[0].refresh_from_db()
        self.assertIsNone(self.docs[0].trashed_at)
        self.assertEqual(self.docs[0].lifecycle_revision, 0)
        self.assertEqual(self.transition('documents', self.docs[1], 'restore', 1).data['code'], 'parent_trashed')
        self.assertEqual(self.transition('documents', self.docs[0], 'restore', 0).data['code'], 'parent_trashed')
        self.assertEqual(self.client.get(self.url(f'applications/{self.app.pk}/documents/')).data, [])
        inspected = self.client.get(self.url(f'applications/{self.app.pk}/documents/'), {'show_trashed': 'true'})
        self.assertEqual(len(inspected.data), 2)
        self.assertTrue(all(d['effective_trashed'] for d in inspected.data))
        self.transition('applications', self.app, 'restore', 1)
        self.assertEqual(list(Document.objects.live().values_list('pk', flat=True)), [self.docs[0].pk])
        self.docs[1].refresh_from_db()
        self.assertEqual(self.docs[1].lifecycle_revision, 1)
        self.transition('documents', self.docs[1], 'restore', 1)
        self.assertEqual(Document.objects.live().count(), 2)
        after = self.snapshot()
        # Evidence mutations may recalculate automatic output; retained manual,
        # history, membership, extraction and file identity remain unchanged.
        for row in (before[0], after[0]):
            row.pop("derived_at")
        self.assertEqual(before, after)
        for pk, name, content in files:
            doc = Document.objects.get(pk=pk)
            self.assertEqual(doc.file.name, name)
            self.assertEqual(doc.file.read(), content)

    def test_visibility_and_mutation_guards(self):
        self.transition('documents', self.docs[1], 'trash', 0)
        with patch('applications.views.assemble_dossier', side_effect=lambda docs: {'eligible': [d.pk for d in docs]}):
            response = self.client.get(self.url(f'applications/{self.app.pk}/dossier/'))
        self.assertEqual(response.data['eligible'], [self.docs[0].pk])
        for action, body in [('rename', {'new_filename': 'changed.txt'}), ('override', {'doc_type_override': 'other'})]:
            self.assertEqual(self.client.post(self.url(f'documents/{self.docs[1].pk}/{action}/'), body).status_code, 409)
        self.transition('applications', self.app, 'trash', 0)
        before = self.snapshot()
        self.assertEqual(self.client.get(self.url('applications/')).data, [])
        self.assertEqual(len(self.client.get(self.url('applications/'), {'show_trashed': 'true'}).data), 1)
        self.assertTrue(self.client.get(self.url(f'applications/{self.app.pk}/')).data['is_trashed'])
        self.assertTrue(self.client.get(self.url(f'documents/{self.docs[0].pk}/')).data['effective_trashed'])
        for suffix, body in [(f'applications/{self.app.pk}/override/', {'notes': 'no'}),
                             ('applications/bulk-override/', {'item_ids': [self.app.pk], 'archived': False}),
                             (f'documents/{self.docs[0].pk}/rename/', {'new_filename': 'no.txt'})]:
            self.assertEqual(self.client.post(self.url(suffix), body, format='json').status_code, 409)
        self.assertEqual(self.client.post(self.url(f'applications/{self.app.pk}/documents/'),
                         {'files': [SimpleUploadedFile('no.txt', b'no')]}).status_code, 409)
        self.assertEqual(self.client.get(self.url(f'applications/{self.app.pk}/dossier/')).status_code, 409)
        self.assertEqual(self.client.get(self.url('search/'), {'q': 'evidence'}).data, [])
        self.assertEqual(self.client.get(self.url('browse/'), {'show_archived': True}).data, {})
        self.assertEqual(self.client.get(self.url('attention/')).data, [])
        self.assertEqual(self.client.get(self.url('insights/')).data['total'], 0)
        self.assertEqual(self.client.get(self.url('manage/')).data['archived'], [])
        self.assertEqual(before, self.snapshot())

    def test_category_not_containment_and_membership_may_leave_but_not_enter(self):
        before = self.snapshot()
        self.transition('categories', self.cat, 'trash', 0)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.client.get(self.url('categories/'), {'show_archived': True}).data, [])
        self.assertEqual(len(self.client.get(self.url('categories/'), {'show_archived': True, 'show_trashed': True}).data), 1)
        self.assertEqual(len(self.client.get(self.url('applications/')).data), 1)
        self.assertEqual(Document.objects.live().count(), 2)
        self.assertEqual(len(self.client.get(self.url('search/'), {'q': 'evidence'}).data), 2)
        self.assertEqual(self.client.get(self.url(f'categories/{self.cat.pk}/applications/')).status_code, 409)
        self.assertEqual(self.client.patch(self.url(f'categories/{self.cat.pk}/'),
                         {'archived': False, 'expected_revision': 0}, format='json', HTTP_IDEMPOTENCY_KEY=uuid.uuid4().hex).status_code, 409)
        path = self.url(f'applications/{self.app.pk}/category/')
        self.assertEqual(self.client.put(path, {'category_id': None, 'expected_revision': 0}, format='json').status_code, 200)
        self.assertEqual(self.client.put(path, {'category_id': self.cat.pk, 'expected_revision': 1}, format='json').status_code, 409)
        self.transition('categories', self.cat, 'restore', 1)
        self.cat.refresh_from_db()
        self.assertTrue(self.cat.archived)
        self.assertFalse(CategoryMembership.objects.exists())
        self.assertEqual(self.client.put(path, {'category_id': self.cat.pk, 'expected_revision': 1}, format='json').status_code, 200)
        self.transition('applications', self.app, 'trash', 0)
        self.assertEqual(self.client.put(path, {'category_id': None, 'expected_revision': 2}, format='json').status_code, 409)

    def test_admin_stale_form_preserves_current_revisions(self):
        from django.test import RequestFactory
        from django.db import transaction
        authority = admin.site._registry[Application]
        stale = Application.objects.get(pk=self.app.pk)
        self.client.put(self.url(f'applications/{self.app.pk}/category/'),
                        {'category_id': None, 'expected_revision': 0}, format='json')
        self.transition('applications', self.app, 'trash', 0)
        self.transition('applications', self.app, 'restore', 1)
        stale.company = 'Allowed admin edit'
        with transaction.atomic():
            authority.save_model(RequestFactory().post('/admin/'), stale, None, True)
        self.app.refresh_from_db()
        self.assertEqual(self.app.company, 'Allowed admin edit')
        self.assertEqual(self.app.lifecycle_revision, 2)
        self.assertEqual(self.app.category_revision, 1)
        self.assertFalse(CategoryMembership.objects.exists())

    def test_scope_auth_and_csrf(self):
        for kind, obj in [('applications', self.app), ('documents', self.docs[0]), ('categories', self.cat)]:
            for ws in (self.other, self.foreign):
                self.assertEqual(self.transition(kind, obj, 'trash', 0, ws).status_code, 404)
                self.assertEqual(self.client.get(self.url(f'{kind}/{obj.pk}/', ws)).status_code, 404)
            url = self.url(f'{kind}/{obj.pk}/trash/')
            self.assertEqual(APIClient().post(url, {'expected_revision': 0}).status_code, 401)
            csrf = APIClient(enforce_csrf_checks=True)
            csrf.force_login(self.user)
            self.assertEqual(csrf.post(url, {'expected_revision': 0}).status_code, 403)
        self.docs[0].workspace = self.other
        self.docs[0].save()
        self.assertEqual(self.transition('documents', self.docs[0], 'trash', 0).status_code, 404)
        self.assertEqual(self.transition('documents', self.docs[0], 'trash', 0, self.other).status_code, 404)

    def test_creation_and_posting_replay_and_trashed_duplicate_candidates(self):
        account = EmailAccount.objects.create(workspace=self.ws, email='fixture@example.test')
        job = JobPosting.objects.create(workspace=self.ws, account=account, company='Posting', title='Role', dedupe_key='fixture')
        for suffix, body, keyfield in [('applications/', {'company': 'Created', 'category_id': self.cat.pk}, 'id'),
                                     (f'job-postings/{job.pk}/apply/', {'category_id': self.cat.pk}, 'application_id')]:
            key = uuid.uuid4().hex
            first = self.client.post(self.url(suffix), body, format='json', HTTP_IDEMPOTENCY_KEY=key)
            self.assertEqual(first.status_code, 201, first.data)
            app = Application.objects.get(pk=first.data[keyfield])
            self.client.put(self.url(f'applications/{app.pk}/category/'), {'category_id': None, 'expected_revision': 1}, format='json')
            self.transition('applications', app, 'trash', 0)
            replay = self.client.post(self.url(suffix), body, format='json', HTTP_IDEMPOTENCY_KEY=key)
            self.assertEqual(replay.status_code, 200)
            self.assertEqual(replay.data[keyfield], app.pk)
            self.assertTrue(replay.data['is_trashed'])
            self.assertFalse(CategoryMembership.objects.filter(application=app).exists())
            warning = self.client.post(self.url(suffix), body, format='json', HTTP_IDEMPOTENCY_KEY=uuid.uuid4().hex)
            self.assertEqual(warning.status_code, 409)
            self.assertTrue(warning.data['candidates'][0]['is_trashed'])
        self.assertEqual(Application.objects.count(), 3)

    def test_category_creation_replay_preserves_trashed_identity(self):
        key = uuid.uuid4().hex
        body = {'name': 'New'}
        first = self.client.post(self.url('categories/'), body, format='json', HTTP_IDEMPOTENCY_KEY=key)
        cat = Category.objects.get(pk=first.data['id'])
        self.transition('categories', cat, 'trash', 0)
        replay = self.client.post(self.url('categories/'), body, format='json', HTTP_IDEMPOTENCY_KEY=key)
        self.assertEqual(replay.data['id'], cat.pk)
        self.assertTrue(replay.data['is_trashed'])
        self.assertEqual(Category.objects.count(), 2)
        self.assertEqual(self.client.post(self.url('applications/'), {'company': 'Blocked', 'category_id': cat.pk},
                         format='json', HTTP_IDEMPOTENCY_KEY=uuid.uuid4().hex).status_code, 409)

    def test_admin_and_ancestor_deletion_cannot_bypass_preservation(self):
        for model in (Application, Document, Category):
            self.assertFalse(admin.site._registry[model].has_delete_permission(None))
        for target in (self.app, self.ws, self.user):
            with self.assertRaises(ProtectedError):
                target.delete()
        self.transition('applications', self.app, 'trash', 0)
        self.app.refresh_from_db()
        self.docs[0].refresh_from_db()
        self.assertFalse(admin.site._registry[Application].has_change_permission(None, self.app))
        self.assertFalse(admin.site._registry[Document].has_change_permission(None, self.docs[0]))


class LifecycleConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='race')
        self.ws = Workspace.objects.create(owner=self.user, name='race')
        self.app = Application.objects.create(workspace=self.ws, company='Race', section='applications')
        self.doc = Document.objects.create(workspace=self.ws, application=self.app, file='fixture/retained',
                                          filename='evidence.txt', ext='.txt', size=1, content_hash='race')
        self.cat = Category.objects.create(workspace=self.ws, name='Race', section='misc')

    def race(self, calls):
        barrier = Barrier(len(calls))
        def run(call):
            close_old_connections()
            client = APIClient()
            client.force_authenticate(User.objects.get(pk=self.user.pk))
            barrier.wait(timeout=10)
            try:
                method, suffix, body = call
                response = getattr(client, method)(f'/api/workspaces/{self.ws.pk}/{suffix}', body, format='json')
                return response.status_code, response.data
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            results = list(pool.map(run, calls))
        for code, data in results:
            self.assertIn(code, (200, 409, 503), data)
        return results

    def transition(self, kind, obj, state, revision):
        return ('post', f'{kind}/{obj.pk}/{state}/', {'expected_revision': revision})

    def test_same_revision_competing_transitions_reconcile(self):
        for kind, obj in [('applications', self.app), ('documents', self.doc), ('categories', self.cat)]:
            results = self.race([self.transition(kind, obj, 'trash', 0), self.transition(kind, obj, 'trash', 0)])
            self.assertLessEqual(sum(code == 200 for code, _ in results), 1)
            obj.refresh_from_db()
            if obj.lifecycle_revision == 0:  # SQLite may reject both admissions.
                set_trash(actor=self.user, workspace=self.ws, kind=kind, pk=obj.pk, trashed=True, expected_revision=0)
            obj.refresh_from_db()
            self.assertTrue(obj.is_trashed)
            self.assertEqual(obj.lifecycle_revision, 1)
            set_trash(actor=self.user, workspace=self.ws, kind=kind, pk=obj.pk, trashed=False, expected_revision=1)

    def test_opposite_desired_states_do_not_consume_revision_twice(self):
        results = self.race([self.transition('applications', self.app, 'trash', 0),
                             self.transition('applications', self.app, 'restore', 0)])
        self.app.refresh_from_db()
        # A restore of the initially live state may complete as a no-op before
        # Trash. It must not consume revision 0 or undo a committed Trash.
        self.assertIn(self.app.lifecycle_revision, (0, 1))
        self.assertEqual(self.app.is_trashed, self.app.lifecycle_revision == 1)
        if results[0][0] == 200:
            self.assertTrue(self.app.is_trashed)
        if results[1][0] == 200:
            self.assertEqual(results[1][1]['lifecycle_revision'], 0)

    def test_parent_trash_racing_child_restore(self):
        set_trash(actor=self.user, workspace=self.ws, kind='documents', pk=self.doc.pk, trashed=True, expected_revision=0)
        self.race([self.transition('applications', self.app, 'trash', 0), self.transition('documents', self.doc, 'restore', 1)])
        self.app.refresh_from_db()
        if not self.app.is_trashed:
            set_trash(actor=self.user, workspace=self.ws, kind='applications', pk=self.app.pk, trashed=True, expected_revision=0)
        self.doc.refresh_from_db()
        self.assertTrue(self.doc.effective_trashed)
        self.assertFalse(Document.objects.live().exists())
        self.assertEqual(Document.objects.count(), 1)
        self.assertIn(self.doc.lifecycle_revision, (1, 2))

    def test_category_trash_racing_assignment(self):
        results = self.race([self.transition('categories', self.cat, 'trash', 0),
                             ('put', f'applications/{self.app.pk}/category/', {'category_id': self.cat.pk, 'expected_revision': 0})])
        self.cat.refresh_from_db()
        if not self.cat.is_trashed:
            set_trash(actor=self.user, workspace=self.ws, kind='categories', pk=self.cat.pk, trashed=True, expected_revision=0)
        self.app.refresh_from_db()
        self.assertFalse(self.app.is_trashed)
        self.assertEqual(CategoryMembership.objects.filter(application=self.app).exists(), results[1][0] == 200)
        self.assertEqual(self.app.category_revision, int(results[1][0] == 200))
        # Membership can precede Trash and survive; admission after Trash cannot commit.
        from documents.category_services import assign_category
        from core.lifecycle import LifecycleConflict
        with self.assertRaises(LifecycleConflict):
            assign_category(actor=self.user, workspace=self.ws, application_id=self.app.pk,
                            category_id=self.cat.pk, expected_revision=self.app.category_revision)

    def test_competing_evidence_writes_leave_derived_committed_snapshot(self):
        from applications.derivation import derive_application
        self.doc.doc_type = 'resume'
        self.doc.save()
        derive_application(actor=self.user, workspace=self.ws, application_id=self.app.pk)
        results = self.race([
            ('post', f'documents/{self.doc.pk}/override/', {'doc_type_override': 'rejection_notice'}),
            ('post', f'documents/{self.doc.pk}/rename/', {'new_filename': 'interview.txt'}),
        ])
        # SQLite may reject both admissions; rejected writes must also leave
        # the previously derived snapshot intact. No automatic mutation retry.
        self.app.refresh_from_db()
        before = (self.app.status, self.app.derivation_fingerprint, self.app.derived_at,
                  list(self.app.status_history.values_list('status', flat=True)))
        # This must be a no-op, not a repair of an intermediate race snapshot.
        derive_application(actor=self.user, workspace=self.ws, application_id=self.app.pk)
        self.app.refresh_from_db()
        self.assertEqual(before, (self.app.status, self.app.derivation_fingerprint, self.app.derived_at,
                                  list(self.app.status_history.values_list('status', flat=True))))
        self.assertEqual(Document.objects.count(), 1)
        self.assertEqual(self.app.lifecycle_revision, 0)

    def test_document_trash_racing_type_change_keeps_eligible_snapshot(self):
        from applications.derivation import derive_application
        self.doc.doc_type = 'resume'
        self.doc.save()
        derive_application(actor=self.user, workspace=self.ws, application_id=self.app.pk)
        self.race([self.transition('documents', self.doc, 'trash', 0),
                   ('post', f'documents/{self.doc.pk}/override/', {'doc_type_override': 'rejection_notice'})])
        self.app.refresh_from_db()
        before = (self.app.status, self.app.derivation_fingerprint, self.app.derived_at, self.app.status_history.count())
        derive_application(actor=self.user, workspace=self.ws, application_id=self.app.pk)
        self.app.refresh_from_db()
        self.assertEqual(before, (self.app.status, self.app.derivation_fingerprint, self.app.derived_at, self.app.status_history.count()))
