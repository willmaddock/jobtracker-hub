"""Whole-review disposition is independent of source, relationships and Trash."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier, Event, local
from unittest.mock import patch

from django.apps import apps
from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError as ModelValidationError
from django.db import IntegrityError, OperationalError, connections, connection, transaction
from django.http import Http404
from django.test import TestCase, TransactionTestCase
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.test import APIClient, APIRequestFactory

from applications.models import (Application, ApplicationMessage, Override,
    RetainedApplicationReview as Review, RetainedApplicationReviewCandidate as Candidate,
    RetainedApplicationReviewDisposition as Disposition)
from applications.message_relationships import attach_message
from applications.retained_reviews import attach_review, set_review_dismissal, disposition_data
from applications.tests.test_review_attach import AttachFixtures
from core.lifecycle import set_trash
from documents.models import Document
from email_sync.models import (AccountMatch, Discovery, EmailAccount, GmailCredential,
                               ThreadIdentifier, RetainedMessage)
from email_sync.tests.test_gmail_adoption import AdoptionFixtures, fetched
from postings.models import JobPosting


class DispositionFixtures(AttachFixtures):
    def setUp(self):
        super().setUp()
        self.review, _ = self.ensure()

    def action_url(self, action='dismiss', ws=None):
        return self.review_url(self.review, ws) + action + '/'

    def transition(self, action='dismiss', revision=0):
        return self.client.post(self.action_url(action), {'expected_revision': revision}, format='json')

    def service(self, dismissed=True, revision=0, **overrides):
        values = dict(actor=self.user, workspace=self.ws, review_id=self.review.pk,
                      dismissed=dismissed, expected_revision=revision)
        values.update(overrides)
        return set_review_dismissal(**values)


class ReviewDispositionTests(DispositionFixtures, TestCase):
    def test_missing_defaults_and_initial_restore_do_not_allocate(self):
        expected = {'state': 'active', 'revision': 0, 'dismissed_at': None}
        self.assertEqual(self.detail(self.review)['disposition'], expected)
        self.assertEqual(self.client.get(self.review_url()).data['results'][0]['disposition'], expected)
        response = self.transition('restore')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'id': self.review.pk, 'workspace_id': self.ws.pk, 'disposition': expected})
        self.assertFalse(Disposition.objects.exists())
        self.assertEqual(self.transition('restore', 1).data['code'], 'stale_revision')
        self.assertFalse(Disposition.objects.exists())

    def test_transitions_noops_timestamps_and_stale_before_noop(self):
        first = self.transition()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data['disposition']['state'], 'dismissed')
        self.assertEqual(first.data['disposition']['revision'], 1)
        self.assertIsNotNone(first.data['disposition']['dismissed_at'])
        self.assertIn('T', first.json()['disposition']['dismissed_at'])
        before = list(Disposition.objects.values())
        self.assertEqual(self.transition(revision=1).data, first.data)
        self.assertEqual(before, list(Disposition.objects.values()))
        stale = self.transition(revision=0)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.data['code'], 'stale_revision')
        self.assertEqual(self.transition('restore', 0).data['code'], 'stale_revision')
        restored = self.transition('restore', 1)
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.data['disposition'], {'state': 'active', 'revision': 2, 'dismissed_at': None})
        self.assertEqual(Disposition.objects.count(), 1)
        self.assertEqual(self.transition('restore', 2).data, restored.data)
        self.assertEqual(self.transition('restore', 1).data['code'], 'stale_revision')
        self.assertEqual(self.transition(revision=2).data['disposition']['revision'], 3)

    def test_auth_csrf_strict_payload_suffix_and_methods(self):
        for action in ('dismiss', 'restore'):
            url = self.action_url(action)
            anonymous = APIClient().post(url, {'expected_revision': 0}, format='json')
            self.assertEqual((anonymous.status_code, anonymous.data['code']), (401, 'authentication_required'))
            csrf = APIClient(enforce_csrf_checks=True)
            csrf.force_login(self.user)
            response = csrf.post(url, {'expected_revision': 0}, format='json')
            self.assertEqual((response.status_code, response.data['code']), (403, 'csrf_failed'))
            invalid = [{}, [], {'revision': 0}]
            invalid += [{'expected_revision': v} for v in (None, -1, True, False, '0', 0.0, [], {}, 2**63)]
            invalid += [{'expected_revision': 0, field: 1} for field in
                        ('workspace_id', 'owner', 'dismissed', 'application_id', 'retained_message_id', 'extra')]
            for body in invalid:
                response = self.client.post(url, body, format='json')
                self.assertEqual((response.status_code, response.data['code']), (400, 'validation_error'), body)
            self.assertEqual(self.client.post(url, '{', content_type='application/json').status_code, 400)
            for method in ('get', 'put', 'patch', 'delete'):
                self.assertEqual(getattr(self.client, method)(url).status_code, 405)
        self.assertFalse(Disposition.objects.exists())
        for action, revision in (('dismiss', 0), ('restore', 1)):
            response = self.client.post(self.action_url(action).rstrip('/') + '.json',
                                        {'expected_revision': revision}, format='json')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['disposition']['revision'], revision + 1)

    def test_service_validation_and_ownership(self):
        for actor in (self.other, AnonymousUser()):
            with self.assertRaises(NotFound):
                self.service(actor=actor)
        for ws in (self.ws_b, self.ws_c):
            with self.assertRaises((NotFound, Http404)):
                self.service(workspace=ws)
            for action in ('dismiss', 'restore'):
                response = self.client.post(self.action_url(action, ws), {'expected_revision': 0}, format='json')
                self.assertEqual((response.status_code, response.data['code']), (404, 'not_found'))
        for key, values in (('review_id', (None, True, 0, -1, '1', 1.0, 2**63)),
                            ('dismissed', (None, 0, 1, 'true')),
                            ('expected_revision', (True, -1, '0', 0.1))):
            for value in values:
                with self.assertRaises(ValidationError):
                    self.service(**{key: value})
        with self.assertRaises(Http404):
            self.service(review_id=9223372036854775807)
        self.assertFalse(Disposition.objects.exists())

    def test_corrupt_scoped_references_rejected_without_side_effects(self):
        observation = self.review.originating_observation
        mutations = [(Review, self.review.pk, 'workspace_id', self.ws_b.pk),
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
            for action in ('dismiss', 'restore'):
                response = self.transition(action)
                self.assertEqual((response.status_code, response.data['code']), (404, 'not_found'), (model, field))
            qs.update(**{field: original})
        self.assertFalse(Disposition.objects.exists())

    def test_zero_one_many_links_and_all_other_tables_preserved(self):
        account = EmailAccount.objects.create(workspace=self.ws, provider='gmail', email='fixture@example.test')
        GmailCredential.objects.create(account=account, access_token='synthetic-ciphertext', refresh_token='synthetic-ciphertext')
        AccountMatch.objects.create(account=account, application=self.app, message_id='<legacy>')
        for kind in ('application', 'posting'):
            discovery = Discovery.objects.create(account=account, kind=kind, message_id=kind, status='dismissed')
            discovery.candidate_applications.add(self.app)
        JobPosting.objects.create(workspace=self.ws, account=account, dedupe_key='preserve')
        ThreadIdentifier.objects.create(application=self.app, message_id='<legacy>')
        Override.objects.create(application=self.app, manual_status='interviewing', notes='preserve', archived=True)
        Document.objects.create(workspace=self.ws, application=self.app, file='synthetic/existing.pdf',
            filename='existing.pdf', ext='.pdf', size=1, content_hash='a' * 64)
        models = [m for m in apps.get_models(include_auto_created=True) if m != Disposition]
        self.assertFalse(Disposition.objects.exists())  # dismissed legacy records do not create disposition
        for count in range(3):
            if count:
                target = self.app if count == 1 else self.application(self.ws)
                self.assertEqual(self.submit(self.review, target).status_code, 201)
            before = [list(m.objects.order_by('pk').values()) for m in models]
            for action, revision in (('dismiss', count * 2), ('restore', count * 2 + 1)):
                self.assertEqual(self.transition(action, revision).status_code, 200)
                self.assertEqual(before, [list(m.objects.order_by('pk').values()) for m in models])
                self.state(self.review, count, 1)

    def test_new_pair_blocked_replay_and_direct_endpoint_independent(self):
        self.assertEqual(self.submit(self.review).status_code, 201)
        self.assertFalse(Disposition.objects.exists())
        original = list(ApplicationMessage.objects.values())
        self.transition()
        state = list(Disposition.objects.values())
        with patch('applications.message_relationships.attach_message', wraps=attach_message) as writer:
            self.assertEqual(self.submit(self.review).status_code, 200)
            writer.assert_called_once()
        self.assertEqual(original, list(ApplicationMessage.objects.values()))
        other = self.application(self.ws)
        blocked = self.submit(self.review, other)
        self.assertEqual((blocked.status_code, blocked.data['code']), (409, 'review_dismissed'))
        self.assertEqual(self.post(app=other).status_code, 201)
        self.assertEqual(self.submit(self.review, other).status_code, 200)
        self.assertEqual(state, list(Disposition.objects.values()))
        self.state(self.review, 2, 1)
        self.transition('restore', 1)
        state = list(Disposition.objects.values())
        self.assertEqual(self.submit(self.review, self.application(self.ws)).status_code, 201)
        self.assertEqual(state, list(Disposition.objects.values()))

    def test_dismissed_foreign_target_and_corrupt_pair_are_not_new_pair(self):
        self.submit(self.review)
        self.transition()
        self.assertEqual(self.submit(self.review, self.application(self.ws_b)).status_code, 404)
        ApplicationMessage.objects.update(workspace=self.ws_b)
        before = list(ApplicationMessage.objects.values())
        response = self.submit(self.review)
        self.assertEqual((response.status_code, response.data['code']), (404, 'not_found'))
        self.assertEqual(before, list(ApplicationMessage.objects.values()))
        self.state(self.review, 0, 1)

    def test_conflict_allows_disposition_but_replay_still_rejects(self):
        self.submit(self.review)
        original = list(ApplicationMessage.objects.values())
        data = deepcopy(self.data)
        data['content']['subject'] = 'conflict'
        self.retain('conflict', data)
        for action, revision in (('dismiss', 0), ('restore', 1)):
            self.assertEqual(self.transition(action, revision).status_code, 200)
            self.assertEqual(self.submit(self.review).data['code'], 'retained_source_ineligible')
        self.assertEqual(self.submit(self.review, self.application(self.ws)).data['code'], 'retained_source_ineligible')
        self.assertEqual(original, list(ApplicationMessage.objects.values()))
        self.state(self.review, 1, 1)

    def test_trash_restore_and_disposition_are_independent(self):
        self.submit(self.review)
        original = list(ApplicationMessage.objects.values())
        self.transition()
        set_trash(actor=self.user, workspace=self.ws, kind='applications', pk=self.app.pk, trashed=True, expected_revision=0)
        self.assertEqual(self.submit(self.review).data['code'], 'resource_trashed')
        self.assertEqual(self.detail(self.review)['relationships'][0]['availability'], 'trashed')
        self.state(self.review, 1, 1)
        self.transition('restore', 1)
        self.app.refresh_from_db()
        self.assertTrue(self.app.is_trashed)
        self.assertEqual(self.submit(self.review).data['code'], 'resource_trashed')
        self.transition('dismiss', 2)
        before = list(Disposition.objects.values())
        set_trash(actor=self.user, workspace=self.ws, kind='applications', pk=self.app.pk, trashed=False, expected_revision=1)
        self.assertEqual(before, list(Disposition.objects.values()))
        self.assertEqual(self.submit(self.review).status_code, 200)
        self.assertEqual(original, list(ApplicationMessage.objects.values()))
        self.assertEqual(self.detail(self.review)['disposition']['state'], 'dismissed')

    def test_inclusive_list_counts_and_candidate_attachability(self):
        other = self.application(self.ws)
        # New source with two immutable initial candidates.
        data = deepcopy(self.data)
        data['source']['value'] = 'two'
        message = self.retain('two', data)
        review, _ = self.ensure([self.app.pk, other.pk], retained_message_id=message.pk,
                                observation_id=message.observations.get().pk)
        self.submit(review)
        self.service(review_id=review.pk)
        detail = self.detail(review)
        candidates = {c['application_id']: c for c in detail['candidates']}
        self.assertTrue(candidates[self.app.pk]['attachable'])
        self.assertFalse(candidates[other.pk]['attachable'])
        rows = self.client.get(self.review_url()).data['results']
        self.assertEqual([r['id'] for r in rows], [self.review.pk, review.pk])
        self.assertEqual([r['disposition']['state'] for r in rows], ['active', 'dismissed'])
        self.assertEqual((detail['candidate_count'], detail['relationship_count']), (2, 1))
        self.assertEqual(self.client.get(self.review_url(), {'after': self.review.pk}).data['results'], [rows[1]])
        self.assertNotIn('handled', detail)

    def test_model_identity_uniqueness_deletion_and_admin_protection(self):
        self.service()
        row = Disposition.objects.get()
        self.assertEqual(row.pk, self.review.pk)
        with self.assertRaises(ModelValidationError):
            row.delete()
        row.pk = None
        with self.assertRaises(ModelValidationError):
            row.save()
        row = Disposition.objects.only('review').get()
        row.pk = self.review.pk + 100
        with self.assertRaises(ModelValidationError):
            row.save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Disposition.objects.bulk_create([Disposition(review=self.review)])
        row = Disposition.objects.get()
        model_admin = admin.site._registry[Disposition]
        request = APIRequestFactory().get('/')
        request.user = self.user
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request, row))
        self.assertFalse(model_admin.has_delete_permission(request, row))
        self.assertFalse(model_admin.get_actions(request))
        self.assertEqual(set(model_admin.get_readonly_fields(request)), {f.name for f in Disposition._meta.fields})

    def test_actual_insert_and_update_failures_roll_back(self):
        save = Disposition.save
        def fail(instance, *args, **kwargs):
            save(instance, *args, **kwargs)
            raise RuntimeError('after disposition write')
        with patch.object(Disposition, 'save', fail), self.assertRaises(RuntimeError):
            self.service()
        self.assertFalse(Disposition.objects.exists())
        self.service()
        before = list(Disposition.objects.values())
        with patch.object(Disposition, 'save', fail), self.assertRaises(RuntimeError):
            self.service(False, 1)
        self.assertEqual(before, list(Disposition.objects.values()))


class ReviewDispositionConcurrencyTests(DispositionFixtures, TransactionTestCase):
    def request(self, action, revision=0):
        client = APIClient()
        client.force_authenticate(self.user)
        return client.post(self.action_url(action), {'expected_revision': revision}, format='json')

    def test_workspace_gate_precedes_disposition_reads_for_both_services(self):
        from applications.creation import lock_workspace
        gated = False
        original_filter = Disposition.objects.filter
        def lock(*args):
            nonlocal gated
            self.assertTrue(connection.in_atomic_block)
            lock_workspace(*args)
            gated = True
        def read(*args, **kwargs):
            self.assertTrue(gated)
            self.assertTrue(connection.in_atomic_block)
            return original_filter(*args, **kwargs)
        for operation in (lambda: self.submit(self.review), lambda: self.transition()):
            gated = False
            with patch('applications.retained_reviews.lock_workspace', side_effect=lock), \
                 patch.object(Disposition.objects, 'filter', side_effect=read):
                self.assertIn(operation().status_code, (200, 201))
        before = list(Disposition.objects.values())
        with patch('applications.retained_reviews.lock_workspace', side_effect=OperationalError('database is locked')):
            for operation in (lambda: self.transition('restore', 1), lambda: self.submit(self.review)):
                response = operation()
                self.assertEqual((response.status_code, response.data['code']), (503, 'lifecycle_busy'))
        self.assertEqual(before, list(Disposition.objects.values()))

    def ordered_race(self, first):
        from applications.creation import lock_workspace
        acquired, attempted, release = Event(), Event(), Event()
        worker = local()
        def gate(*args):
            if worker.winner:
                lock_workspace(*args)
                acquired.set()
                if not release.wait(10):
                    raise AssertionError('winner not released')
            else:
                attempted.set()
                lock_workspace(*args)
        def run(action, winner):
            connections.close_all()
            worker.winner = winner
            try:
                # Exercise service admission directly: SQLite may refuse the API's
                # initial Workspace lookup before the contender reaches this gate.
                if action == 'attach':
                    _, created = attach_review(actor=self.user, workspace=self.ws,
                        review_id=self.review.pk, application_id=self.app.pk)
                    return 201 if created else 200
                self.service()
                return 200
            except OperationalError as exc:
                if connection.vendor != 'sqlite' or 'locked' not in str(exc).lower():
                    raise
                return 503
            except APIException as exc:
                return exc.status_code
            finally:
                connections.close_all()
        second = 'dismiss' if first == 'attach' else 'attach'
        with patch('applications.retained_reviews.lock_workspace', side_effect=gate):
            with ThreadPoolExecutor(max_workers=2) as pool:
                winner = pool.submit(run, first, True)
                try:
                    self.assertTrue(acquired.wait(10))
                    loser = pool.submit(run, second, False)
                    self.assertTrue(attempted.wait(10))
                finally:
                    release.set()
                results = winner.result(timeout=10), loser.result(timeout=10)
        return results

    def test_attach_wins_then_dismiss_preserves_committed_pair(self):
        attached, dismissed = self.ordered_race('attach')
        self.assertEqual(attached, 201)
        self.assertIn(dismissed, (200, 503))
        before = list(ApplicationMessage.objects.values())
        if dismissed == 503:
            self.assertEqual(self.transition().status_code, 200)
        self.assertEqual(before, list(ApplicationMessage.objects.values()))
        self.assertEqual(self.submit(self.review).status_code, 200)
        self.state(self.review, 1, 1)
        self.assertEqual(Disposition.objects.get().revision, 1)

    def test_dismiss_wins_then_new_pair_cannot_commit(self):
        dismissed, attached = self.ordered_race('dismiss')
        self.assertEqual(dismissed, 200)
        self.assertIn(attached, (409, 503))
        self.assertEqual(self.submit(self.review).data['code'], 'review_dismissed')
        self.assertFalse(ApplicationMessage.objects.exists())
        self.assertEqual(Disposition.objects.get().revision, 1)

    def test_competing_revision_requests_and_opposite_noop(self):
        for actions in (('dismiss', 'dismiss'), ('dismiss', 'restore')):
            # Restore prior round, then both requests share the current revision.
            current = disposition_data(Disposition.objects.first())
            if current['state'] == 'dismissed':
                self.service(False, current['revision'])
            revision = disposition_data(Disposition.objects.first())['revision']
            barrier = Barrier(2)
            def run(action):
                connections.close_all()
                barrier.wait(10)
                try:
                    return self.request(action, revision)
                finally:
                    connections.close_all()
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(run, actions))
            self.assertTrue(all(r.status_code in (200, 409, 503) for r in results))
            current = disposition_data(Disposition.objects.first())
            self.assertIn(current['revision'], (revision, revision + 1))
            if actions == ('dismiss', 'dismiss'):
                self.assertLessEqual(sum(r.status_code == 200 for r in results), 1)
            if results[0].status_code == 200:
                self.assertEqual(current['state'], 'dismissed')
            if actions[1] == 'restore' and results[1].status_code == 200:
                self.assertEqual(results[1].data['disposition']['revision'], revision)


class ReviewDispositionSyncTests(AdoptionFixtures, TestCase):
    def test_gmail_replay_and_changed_matching_preserve_dismissed_review(self):
        self.sync(fetched())
        review = Review.objects.get()
        set_review_dismissal(actor=self.user, workspace=self.ws, review_id=review.pk,
                            dismissed=True, expected_revision=0)
        models = (Review, Candidate, Disposition, ApplicationMessage, AccountMatch, Discovery,
                  Discovery.candidate_applications.through, ThreadIdentifier)
        before = [list(m.objects.values()) for m in models]
        self.app.company = 'Unrelated'
        self.app.role_label = 'Changed'
        self.app.save()
        self.sync(fetched())
        self.assertEqual(before, [list(m.objects.values()) for m in models])
        self.assertFalse(RetainedMessage.objects.get().has_conflict)
