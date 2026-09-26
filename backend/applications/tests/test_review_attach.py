"""Explicit attachment and derived review state using isolated fixtures."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from unittest.mock import patch
from django.apps import apps
from django.db import OperationalError, connection, connections
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient
from applications.models import Application, ApplicationMessage, RetainedApplicationReview as Review
from applications.tests.test_retained_reviews import ReviewFixtures
from core.lifecycle import set_trash
from applications.models import Override
from applications.retained_reviews import attach_review
from documents.models import Document, Category, CategoryMembership
from email_sync.models import AccountMatch, Discovery, EmailAccount, ThreadIdentifier
from email_sync.tests.test_gmail_adoption import AdoptionFixtures, fetched
from applications.models import RetainedApplicationReviewCandidate as Candidate
from django.utils import timezone


class AttachFixtures(ReviewFixtures):
    def endpoint(self, review, ws=None):
        return self.review_url(review, ws) + 'attach/'

    def submit(self, review, app=None):
        return self.client.post(self.endpoint(review), {'application_id': (app or self.app).pk}, format='json')

    def state(self, review, count, candidates):
        for data in (self.detail(review), self.client.get(self.review_url()).data['results'][0]):
            self.assertEqual(data['attachment_status'], 'attached' if count else 'unattached')
            self.assertEqual(data['relationship_count'], count)
            self.assertEqual(data['candidate_count'], candidates)


class ReviewAttachTests(AttachFixtures, TestCase):
    def test_zero_one_many_and_outside_snapshot_explicit_selection(self):
        other, outside = self.application(self.ws), self.application(self.ws)
        for n, ids in enumerate(([], [self.app.pk], [self.app.pk, other.pk])):
            data = deepcopy(self.data)
            data['source']['value'] = str(n)
            message = self.retain(str(n), data)
            review, _ = self.ensure(ids, retained_message_id=message.pk, observation_id=message.observations.get().pk)
            before = list(review.candidates.values()), list(Review.objects.filter(pk=review.pk).values())
            self.assertEqual(self.client.post(self.endpoint(review), {}, format='json').status_code, 400)
            self.assertFalse(message.application_relationships.exists())
            response = self.submit(review, outside)
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.data['application_id'], outside.pk)
            self.assertEqual(response.data['relationship_count'], 1)
            self.assertEqual(before, (list(review.candidates.values()), list(Review.objects.filter(pk=review.pk).values())))

    def test_distinct_attempts_cross_api_replay_and_join_counts(self):
        other, third = self.application(self.ws), self.application(self.ws)
        review, _ = self.ensure([self.app.pk, other.pk])
        self.state(review, 0, 2)
        self.assertEqual(self.post().status_code, 201)
        self.state(review, 1, 2)
        self.assertEqual(self.submit(review).status_code, 200)
        self.assertEqual(self.submit(review).data['id'], self.post().data['id'])
        for app in (other, third):
            self.assertEqual(self.submit(review, app).status_code, 201)
        before = list(ApplicationMessage.objects.values())
        self.assertEqual(self.submit(review, third).status_code, 200)
        self.assertEqual(self.post(app=third).status_code, 200)
        self.assertEqual(before, list(ApplicationMessage.objects.values()))
        self.state(review, 3, 2)
        self.assertEqual(len(self.detail(review)['relationships']), 3)
        self.assertEqual(Application.objects.count(), 3)

    def test_auth_csrf_strict_payload_scoping_suffix_and_methods(self):
        review, _ = self.ensure()
        url = self.endpoint(review)
        self.assertEqual(APIClient().post(url, {}, format='json').status_code, 401)
        csrf = APIClient(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        self.assertEqual(csrf.post(url, {'application_id': self.app.pk}, format='json').status_code, 403)
        invalid = [{}, [], {'retained_message_id': self.message.pk}]
        invalid += [{'application_id': x} for x in (True, False, None, '1', 1.0, 0, -1, 2**63, [], {})]
        invalid += [{'application_id': self.app.pk, k: 1} for k in ('workspace_id', 'owner', 'retained_message_id', 'observation_id', 'origin', 'extra')]
        for payload in invalid:
            self.assertEqual(self.client.post(url, payload, format='json').status_code, 400, payload)
        self.assertEqual(self.client.post(url, '{', content_type='application/json').status_code, 400)
        for ws in (self.ws_b, self.ws_c):
            self.assertEqual(self.submit(review, self.application(ws)).status_code, 404)
            self.assertEqual(self.client.post(self.endpoint(review, ws), {'application_id': self.app.pk}, format='json').status_code, 404)
        self.assertEqual(self.client.post(url, {'application_id': 9223372036854775807}, format='json').status_code, 404)
        for bad in ('nope', '-1', '0', str(2**63)):
            self.assertIn(self.client.post(url.replace(f'/{review.pk}/attach', f'/{bad}/attach'), {'application_id': self.app.pk}, format='json').status_code, (400, 404))
        for method in ('get', 'put', 'patch', 'delete'):
            self.assertEqual(getattr(self.client, method)(url).status_code, 405)
        self.assertFalse(ApplicationMessage.objects.exists())
        self.assertEqual(self.client.post(url.rstrip('/') + '.json', {'application_id': self.app.pk}, format='json').status_code, 201)

    def test_corrupt_provenance_and_relationship_scope(self):
        review, _ = self.ensure()
        observation = review.originating_observation
        mutations = [(Review, review.pk, 'workspace_id', self.ws_b.pk),
            (type(self.message), self.message.pk, 'workspace_id', self.ws_b.pk),
            (type(self.mailbox), self.mailbox.pk, 'workspace_id', self.ws_b.pk),
            (type(observation), observation.pk, 'message_id', None),
            (type(observation), observation.pk, 'mailbox_id', None),
            (type(observation), observation.pk, 'workspace_id', self.ws_b.pk),
            (type(observation.key), observation.key_id, 'workspace_id', self.ws_b.pk)]
        for model, pk, field, value in mutations:
            qs = model.objects.filter(pk=pk)
            original = qs.values_list(field, flat=True).get()
            qs.update(**{field: value})
            self.assertEqual(self.submit(review).status_code, 404, (model, field))
            self.assertEqual(self.client.get(self.review_url()).data['results'], [])
            qs.update(**{field: original})
        self.submit(review)
        ApplicationMessage.objects.update(workspace=self.ws_b)
        self.state(review, 0, 1)
        self.assertEqual(self.detail(review)['relationships'], [])
        self.assertEqual(self.submit(review).status_code, 404)
        ApplicationMessage.objects.update(workspace=self.ws)
        Application.objects.filter(pk=self.app.pk).update(workspace=self.ws_b)
        self.state(review, 0, 1)
        self.assertEqual(self.detail(review)['relationships'], [])
        self.assertEqual(self.submit(review).status_code, 404)

    def test_trash_restore_conflict_and_replay(self):
        review, _ = self.ensure()
        def lifecycle(state, revision):
            set_trash(actor=self.user, workspace=self.ws, kind='applications', pk=self.app.pk, trashed=state, expected_revision=revision)
        lifecycle(True, 0)
        self.assertEqual(self.submit(review).data['code'], 'resource_trashed')
        self.state(review, 0, 1)
        lifecycle(False, 1)
        first = self.submit(review)
        before = list(ApplicationMessage.objects.values())
        lifecycle(True, 2)
        self.assertEqual(self.submit(review).status_code, 409)
        self.state(review, 1, 1)
        self.assertEqual(self.detail(review)['relationships'][0]['availability'], 'trashed')
        lifecycle(False, 3)
        self.assertEqual(self.submit(review).data, first.data)
        data = deepcopy(self.data)
        data['content']['subject'] = 'conflicting source'
        self.retain('conflict', data)
        for app in (self.app, self.application(self.ws)):
            response = self.submit(review, app)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.data['code'], 'retained_source_ineligible')
        self.state(review, 1, 1)
        self.assertEqual(before, list(ApplicationMessage.objects.values()))

    def test_partial_content_and_nonpipeline_target(self):
        data = deepcopy(self.data)
        data['source']['value'] = 'partial'
        data['content']['text'] = {'value': 'Part', 'completeness': 'partial', 'reason': 'provider_limit'}
        message = self.retain('partial', data)
        review, _ = self.ensure([], retained_message_id=message.pk, observation_id=message.observations.get().pk)
        Override.objects.create(application=self.app, archived=True)
        category = Category.objects.create(workspace=self.ws, name='Archived', section='misc',
                                           archived=True, trashed_at=timezone.now())
        CategoryMembership.objects.create(application=self.app, category=category)
        self.app.section = 'misc'
        self.app.save()
        self.assertEqual(self.submit(review).status_code, 201)

    def test_all_other_tables_unchanged_and_insert_failure_rollback(self):
        review, _ = self.ensure()
        account = EmailAccount.objects.create(workspace=self.ws, provider='gmail', email='fixture@example.test')
        AccountMatch.objects.create(account=account, application=self.app, message_id='<legacy>')
        for kind in ('application', 'posting'):
            discovery = Discovery.objects.create(account=account, message_id=f'<{kind}>', kind=kind, status='dismissed')
            discovery.candidate_applications.add(self.app)
        ThreadIdentifier.objects.create(application=self.app, message_id='<legacy>')
        Override.objects.create(application=self.app, manual_status='interviewing', archived=True,
                                date_applied_mode='manual', date_applied='2026-09-01', activity_override='2026-09-02')
        Document.objects.create(workspace=self.ws, application=self.app, file='synthetic/existing.pdf',
                                filename='existing.pdf', ext='.pdf', size=1, content_hash='a' * 64)
        models = [m for m in apps.get_models(include_auto_created=True) if m != ApplicationMessage]
        before = [list(m.objects.order_by('pk').values()) for m in models]
        save = ApplicationMessage.save
        def fail(instance, *args, **kwargs):
            save(instance, *args, **kwargs)
            raise RuntimeError('after insert')
        with patch.object(ApplicationMessage, 'save', fail), self.assertRaises(RuntimeError):
            self.submit(review)
        self.assertFalse(ApplicationMessage.objects.exists())
        self.assertEqual(before, [list(m.objects.order_by('pk').values()) for m in models])
        self.assertEqual(self.submit(review).status_code, 201)
        self.assertEqual(before, [list(m.objects.order_by('pk').values()) for m in models])

    def test_lost_response_replays_committed_identity(self):
        review, _ = self.ensure()
        with patch('applications.review_views.relationship_data', side_effect=RuntimeError('response failure')), self.assertRaises(RuntimeError):
            self.submit(review)
        before = list(ApplicationMessage.objects.values())
        self.assertEqual(self.submit(review).status_code, 200)
        self.assertEqual(before, list(ApplicationMessage.objects.values()))


class ReviewAttachConcurrencyTests(AttachFixtures, TransactionTestCase):
    def race(self, operations):
        barrier = Barrier(len(operations))
        def run(operation):
            connections.close_all()
            barrier.wait(timeout=10)
            try:
                return operation()
            except OperationalError as exc:
                if connection.vendor != 'sqlite' or 'locked' not in str(exc).lower():
                    raise
                return 'locked'
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            return list(pool.map(run, operations))

    def request(self, review, app):
        client = APIClient()
        client.force_authenticate(self.user)
        return client.post(self.endpoint(review), {'application_id': app.pk}, format='json').status_code

    def test_same_and_different_pairs(self):
        review, _ = self.ensure()
        outcomes = self.race([lambda: self.request(review, self.app)] * 2)
        self.assertTrue(all(x in (200, 201, 503) for x in outcomes), outcomes)
        self.assertLessEqual(outcomes.count(201), 1)
        self.submit(review)
        before = ApplicationMessage.objects.get()
        other = self.application(self.ws)
        outcomes = self.race([lambda: self.request(review, self.app), lambda: self.request(review, other)])
        self.assertTrue(all(x in (200, 201, 503) for x in outcomes), outcomes)
        self.submit(review, other)
        self.assertEqual(self.submit(review).data['id'], before.pk)
        self.state(review, 2, 1)

    def test_competing_trash_and_source_conflict(self):
        review, _ = self.ensure()
        def trash():
            set_trash(actor=self.user, workspace=self.ws, kind='applications', pk=self.app.pk, trashed=True, expected_revision=0)
            return 'trashed'
        outcomes = self.race([lambda: self.request(review, self.app), trash])
        self.assertTrue(all(x in (201, 409, 503, 'locked', 'trashed') for x in outcomes), outcomes)
        self.app.refresh_from_db()
        if self.app.is_trashed:
            self.assertEqual(self.submit(review).status_code, 409)
        else:
            trash()
        self.state(review, ApplicationMessage.objects.count(), 1)
        set_trash(actor=self.user, workspace=self.ws, kind='applications', pk=self.app.pk, trashed=False, expected_revision=1)
        data = deepcopy(self.data)
        data['content']['subject'] = 'conflict'
        def conflict():
            self.retain('conflict', data)
            return 'conflict'
        outcomes = self.race([lambda: self.request(review, self.app), conflict])
        self.assertTrue(all(x in (200, 201, 409, 503, 'locked', 'conflict') for x in outcomes), outcomes)
        conflict()
        before = list(ApplicationMessage.objects.values())
        self.assertEqual(self.submit(review).data['code'], 'retained_source_ineligible')
        self.assertEqual(before, list(ApplicationMessage.objects.values()))

    def test_no_outer_transaction_and_lock_refusal(self):
        review, _ = self.ensure()
        from applications.message_relationships import attach_message
        def delegate(**kwargs):
            self.assertFalse(connection.in_atomic_block)
            return attach_message(**kwargs)
        with patch('applications.message_relationships.attach_message', side_effect=delegate):
            self.assertEqual(self.submit(review).status_code, 201)
        with patch('applications.message_relationships.lock_workspace', side_effect=OperationalError('database is locked')):
            response = self.submit(review)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['code'], 'lifecycle_busy')
        self.assertEqual(self.submit(review).status_code, 200)


class ReviewAttachSyncTests(AdoptionFixtures, TestCase):
    def test_attach_then_changed_matching_and_gmail_replay_preserve_snapshot(self):
        self.sync(fetched())
        review = Review.objects.get()
        outside = Application.objects.create(workspace=self.ws, section='applications',
                                              company='Outside', role_label='Snapshot')
        attach_review(actor=self.user, workspace=self.ws, review_id=review.pk, application_id=outside.pk)
        models = (Review, Candidate, ApplicationMessage, AccountMatch, Discovery,
                  Discovery.candidate_applications.through, ThreadIdentifier)
        before = [list(m.objects.values()) for m in models]
        self.app.company = 'Unrelated'
        self.app.role_label = 'Changed'
        self.app.save()
        self.sync(fetched())
        self.assertEqual(before, [list(m.objects.values()) for m in models])
        self.assertFalse(review.retained_message.has_conflict)
