"""Canonical suggestion provenance, read isolation and synthetic Gmail integration."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from unittest.mock import patch
import uuid

from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError as ModelValidationError
from django.db import IntegrityError, OperationalError, connection, connections, transaction
from django.http import Http404
from django.test import TestCase, TransactionTestCase
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.test import APIClient, APIRequestFactory

from applications.message_relationships import SourceIneligible
from applications.models import (Application, ApplicationMessage, RetainedApplicationReview as Review,
                                 RetainedApplicationReviewCandidate as Candidate)
from applications.retained_reviews import ensure_application_review
from applications.tests.test_messages import Fixtures
from core.lifecycle import set_trash
from email_sync.models import AccountMatch, Discovery, RetainedMessage, RetainedObservation, RetentionKey
from email_sync.tests.test_gmail_adoption import AdoptionFixtures, fetched


class ReviewFixtures(Fixtures):
    def ensure(self, candidates=None, classification=None, **overrides):
        ids = [self.app.pk] if candidates is None else candidates
        values = dict(actor=self.user, workspace=self.ws, retained_message_id=self.message.pk,
                      observation_id=self.message.observations.order_by("pk").first().pk,
                      classification=classification or ('match' if len(set(ids)) == 1 else 'ambiguous' if ids else 'application'),
                      candidate_ids=ids)
        values.update(overrides)
        return ensure_application_review(**values)

    def review_url(self, row=None, ws=None):
        base = f'/api/workspaces/{(ws or self.ws).pk}/application-reviews/'
        return base + f'{row.pk}/' if row else base

    def detail(self, row):
        response = self.client.get(self.review_url(row))
        self.assertEqual(response.status_code, 200)
        return response.data


class ReviewTests(ReviewFixtures, TestCase):
    def test_first_snapshot_distinct_attempts_deduplication_and_replay(self):
        other = self.application(self.ws)
        row, created = self.ensure([other.pk, self.app.pk, other.pk])
        self.assertTrue(created)
        self.assertIsInstance(row.portable_id, uuid.UUID)
        self.assertEqual(row.workspace, self.ws)
        before = list(Review.objects.values()), list(Candidate.objects.values())
        # A later changed matching set (even no matches) cannot rewrite history.
        self.app.company = 'Changed'
        self.app.role_label = 'New facts'
        self.app.save()
        replay, created = self.ensure([])
        self.assertFalse(created)
        self.assertEqual(row.pk, replay.pk)
        self.assertEqual(before, (list(Review.objects.values()), list(Candidate.objects.values())))
        self.assertEqual(set(row.candidates.values_list('application_portable_id', flat=True)),
                         {self.app.portable_id, other.portable_id})
        self.assertFalse(ApplicationMessage.objects.exists())
        detail = self.detail(row)
        self.assertEqual(detail['candidate_count'], 2)
        self.assertEqual(detail['initial_classification'], 'ambiguous')

    def test_zero_snapshot_does_not_gain_candidate(self):
        row, _ = self.ensure([])
        self.ensure()
        self.assertEqual(self.detail(row)['candidates'], [])
        self.assertEqual(row.initial_classification, 'application')

    def test_single_snapshot_does_not_gain_ambiguity(self):
        row, _ = self.ensure()
        other = self.application(self.ws)
        self.ensure([self.app.pk, other.pk])
        self.assertEqual(list(row.candidates.values_list('application_id', flat=True)), [self.app.pk])
        self.assertEqual(self.detail(row)['initial_classification'], 'match')

    def test_scope_and_invalid_input_rejected_without_partial_state(self):
        for ws in (self.ws_b, self.ws_c):
            with self.assertRaises((NotFound, Http404)):
                self.ensure([self.application(ws).pk])
        for actor in (self.other, AnonymousUser()):
            with self.assertRaises((NotFound, Http404)):
                self.ensure(actor=actor)
        with self.assertRaises((NotFound, Http404)):
            self.ensure(workspace=self.ws_b)
        for overrides in ({'candidate_ids': [True]}, {'candidate_ids': ['1']},
                          {'retained_message_id': 2**63}, {'observation_id': None},
                          {'classification': 'posting'}, {'classification': 'ambiguous'},
                          {'candidate_ids': {}, 'classification': 'application'}):
            with self.assertRaises(ValidationError):
                self.ensure(**overrides)
        self.assertFalse(Review.objects.exists())
        self.assertFalse(Candidate.objects.exists())
        # Replays also revalidate references instead of accepting foreign inputs.
        self.ensure()
        with self.assertRaises((NotFound, Http404)):
            self.ensure([self.application(self.ws_b).pk])

    def test_observation_must_reference_same_canonical_source(self):
        data = deepcopy(self.data)
        data['source']['value'] = 'another'
        other = self.retain('another', data)
        with self.assertRaises((NotFound, Http404)):
            self.ensure(observation_id=other.observations.get().pk)
        data['source'] = None
        unresolved = self.retain('unresolved', data)
        with self.assertRaises((NotFound, Http404)):
            self.ensure(observation_id=unresolved.observation_id)
        self.assertFalse(Review.objects.exists())
        self.assertEqual(RetainedMessage.objects.count(), 2)

    def test_conflict_preserves_review_snapshot_and_relationship_context(self):
        self.attach()
        row, _ = self.ensure()
        before = list(Review.objects.values()), list(Candidate.objects.values()), list(ApplicationMessage.objects.values())
        data = deepcopy(self.data)
        data['content']['subject'] = 'Conflict'
        self.retain('conflict', data)
        detail = self.detail(row)
        self.assertEqual(detail['retained_message']['state'], 'conflict')
        self.assertFalse(detail['retained_message']['eligible'])
        self.assertFalse(detail['candidates'][0]['attachable'])
        self.assertEqual(detail['relationships'][0]['id'], ApplicationMessage.objects.get().pk)
        with self.assertRaises(SourceIneligible):
            self.attach()
        self.ensure(observation_id=self.message.observations.order_by('pk').first().pk)
        self.assertEqual(before, (list(Review.objects.values()), list(Candidate.objects.values()), list(ApplicationMessage.objects.values())))

    def test_initial_conflict_cannot_allocate_snapshot(self):
        data = deepcopy(self.data)
        data['content']['subject'] = 'Conflict'
        self.retain('conflict', data)
        with self.assertRaises(ValidationError):
            self.ensure(observation_id=self.message.observations.order_by('pk').first().pk)
        self.assertFalse(Review.objects.exists())

    def test_trash_restore_current_availability_preserves_provenance(self):
        self.attach()
        row, _ = self.ensure()
        models = (Review, Candidate, RetainedMessage, RetainedObservation, ApplicationMessage)
        before = [list(model.objects.values()) for model in models]
        for trashed, revision in [(True, 0), (False, 1)]:
            set_trash(actor=self.user, workspace=self.ws, kind='applications', pk=self.app.pk,
                      trashed=trashed, expected_revision=revision)
            detail = self.detail(row)
            self.assertEqual(detail['candidates'][0]['availability'], 'trashed' if trashed else 'live')
            self.assertEqual(detail['candidates'][0]['attachable'], not trashed)
            self.assertEqual(len(detail['relationships']), 1)
            self.ensure()
            self.assertEqual(before, [list(model.objects.values()) for model in models])

    def test_nullable_target_retains_portable_provenance(self):
        row, _ = self.ensure()
        candidate = row.candidates.get()
        # Privileged fixture deletion only, exercising FK policy; no purge API.
        Application.objects.filter(pk=self.app.pk).delete()
        candidate.refresh_from_db()
        self.assertIsNone(candidate.application_id)
        self.assertEqual(candidate.application_portable_id, self.app.portable_id)
        detail = self.detail(row)['candidates'][0]
        self.assertEqual(detail['availability'], 'removed')
        self.assertFalse(detail['attachable'])

    def test_api_scope_auth_read_only_and_safe_content(self):
        row, _ = self.ensure()
        self.assertEqual(APIClient().get(self.review_url()).status_code, 401)
        self.assertEqual(APIClient().get(self.review_url(row)).status_code, 401)
        self.assertEqual(self.client.get(self.review_url(ws=self.ws_b)).data['results'], [])
        for ws in (self.ws_b, self.ws_c):
            self.assertEqual(self.client.get(self.review_url(row, ws)).status_code, 404)
        self.assertEqual(self.client.get(self.review_url(ws=self.ws_c)).status_code, 404)
        self.assertEqual(self.client.get(self.review_url(), {'workspace_id': self.ws_b.pk}).status_code, 400)
        self.assertEqual(self.client.get(self.review_url(), {'after': '-1'}).status_code, 400)
        for url in (self.review_url(), self.review_url(row)):
            for method in ('post', 'put', 'patch', 'delete'):
                self.assertEqual(getattr(self.client, method)(url, {}, format='json').status_code, 405)
        for action in ('accept', 'dismiss', 'restore', 'resolve', 'reevaluate'):
            self.assertEqual(self.client.post(self.review_url(row) + action + '/', {}, format='json').status_code, 404)
        detail = self.detail(row)
        self.assertNotIn('content', detail['retained_message'])
        self.assertNotIn('html', detail)
        self.assertEqual(self.client.get(self.review_url(row).rstrip('/') + '.json').status_code, 200)
        source = self.client.get(f'/api/workspaces/{self.ws.pk}/retained-messages/{self.message.pk}/')
        self.assertEqual(source.status_code, 200)
        self.assertNotIn('value', source.data['content']['html'])

    def test_corrupt_redundant_scope_is_hidden(self):
        row, _ = self.ensure()
        Candidate.objects.filter(review=row).update(application=self.application(self.ws_b))
        self.assertEqual(self.detail(row)['candidates'], [])
        Review.objects.filter(pk=row.pk).update(workspace=self.ws_b)
        self.assertEqual(self.client.get(self.review_url()).data['results'], [])
        self.assertEqual(self.client.get(self.review_url(row, self.ws_b)).status_code, 404)
        with self.assertRaises((NotFound, Http404)):
            self.ensure()

    def test_database_constraints_and_model_admin_immutability(self):
        row, _ = self.ensure()
        candidate = row.candidates.get()
        for obj in (row, candidate):
            with self.assertRaises(ModelValidationError):
                obj.save()
            with self.assertRaises(ModelValidationError):
                obj.delete()
            model_admin = admin.site._registry[type(obj)]
            request = APIRequestFactory().get('/')
            request.user = self.user
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request, obj))
            self.assertFalse(model_admin.has_delete_permission(request, obj))
            self.assertFalse(model_admin.get_actions(request))
            self.assertEqual(set(model_admin.get_readonly_fields(request)), {f.name for f in obj._meta.fields})
        with self.assertRaises(IntegrityError), transaction.atomic():
            Candidate.objects.bulk_create([Candidate(review=row, application=self.app, application_portable_id=self.app.portable_id)])
        with self.assertRaises(IntegrityError), transaction.atomic():
            Review.objects.bulk_create([Review(workspace=self.ws, retained_message=self.message,
                originating_observation=row.originating_observation, initial_classification='application')])
        with self.assertRaises(ModelValidationError):
            Candidate.objects.create(review=row, application=self.application(self.ws_b), application_portable_id=uuid.uuid4())
        candidate.pk = None
        with self.assertRaises(ModelValidationError):
            candidate.save()

    def test_snapshot_failure_rolls_back_all_candidates_and_review(self):
        other = self.application(self.ws)
        save = Candidate.save
        def fail(instance, *args, **kwargs):
            save(instance, *args, **kwargs)
            raise RuntimeError('synthetic post-insert failure')
        models = (Application, ApplicationMessage, RetainedMessage, RetainedObservation, RetentionKey)
        before = [list(model.objects.values()) for model in models]
        with patch.object(Candidate, 'save', fail), self.assertRaises(RuntimeError):
            self.ensure([self.app.pk, other.pk])
        self.assertFalse(Review.objects.exists())
        self.assertFalse(Candidate.objects.exists())
        self.assertEqual(before, [list(model.objects.values()) for model in models])
        self.assertTrue(self.ensure([self.app.pk, other.pk])[1])

    def test_queue_pagination(self):
        for n in range(51):
            data = deepcopy(self.data)
            data['source']['value'] = str(n)
            message = self.retain(str(n), data)
            self.ensure(retained_message_id=message.pk, observation_id=message.observations.get().pk)
        first = self.client.get(self.review_url()).data
        second = self.client.get(self.review_url(), {'after': first['next_after']}).data
        self.assertEqual(len(first['results']), 50)
        self.assertEqual(len(second['results']), 1)
        self.assertIsNone(second['next_after'])


class ReviewConcurrencyTests(ReviewFixtures, TransactionTestCase):
    def test_competing_creation_converges_or_exposes_sqlite_refusal(self):
        barrier = Barrier(2)
        def run(_):
            connections.close_all()
            barrier.wait(timeout=10)
            try:
                return self.ensure()[1]
            except OperationalError as exc:
                if connection.vendor != 'sqlite' or 'locked' not in str(exc).lower():
                    raise
                return 'locked'
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(run, range(2)))
        self.assertLessEqual(outcomes.count(True), 1)
        row, _ = self.ensure()
        self.assertFalse(self.ensure()[1])
        self.assertEqual(Review.objects.count(), 1)
        self.assertEqual(row.candidates.count(), 1)


class ReviewSyncTests(AdoptionFixtures, TestCase):
    def test_single_ambiguous_zero_and_posting_classifications(self):
        self.sync(fetched(native='single', rfc='<single>'))
        other = Application.objects.create(workspace=self.ws, section='applications',
            company=self.app.company, role_label=self.app.role_label)
        self.sync(fetched(native='ambiguous', rfc='<ambiguous>'))
        self.sync(fetched(native='zero', rfc='<zero>', subject='Thank you for applying', body='Your application was received'))
        self.sync(fetched(native='posting', rfc='<posting>', subject='Acme Robotics just posted a 92% match Engineer', body='Open jobs'))
        self.assertEqual(RetainedMessage.objects.count(), 4)
        self.assertEqual(Review.objects.count(), 3)
        rows = {r.retained_message.locator_value: r for r in Review.objects.all()}
        self.assertEqual(rows['single'].candidates.count(), 1)
        self.assertEqual(rows['ambiguous'].candidates.count(), 2)
        self.assertEqual(rows['zero'].candidates.count(), 0)
        self.assertEqual(set(rows['ambiguous'].candidates.values_list('application_id', flat=True)), {self.app.pk, other.pk})
        self.assertFalse(ApplicationMessage.objects.exists())
        self.assertEqual(AccountMatch.objects.count(), 1)
        self.assertEqual(Discovery.objects.count(), 3)
        self.assertEqual(Discovery.objects.get(message_id='<ambiguous>').candidate_applications.count(), 2)
        self.assertEqual(Discovery.objects.get(message_id='<posting>').kind, 'posting')

    def test_no_rfc_and_shared_rfc_are_independent_reviews(self):
        self.sync(fetched(native='a'), fetched(native='b'), fetched(native='c', rfc=None))
        self.assertEqual(Review.objects.count(), 3)
        self.assertEqual(Candidate.objects.count(), 3)
        self.assertEqual(AccountMatch.objects.count(), 1)

    def test_sync_replay_and_changed_matching_facts_do_not_rewrite(self):
        message = fetched()
        self.sync(message)
        before = list(Review.objects.values()), list(Candidate.objects.values())
        self.app.company = 'Different'
        self.app.role_label = 'Different'
        self.app.save()
        self.sync(message, fetched())
        self.assertEqual(before, (list(Review.objects.values()), list(Candidate.objects.values())))

    def test_conflict_and_unresolved_do_not_fabricate_review(self):
        self.sync(fetched(native=None))
        self.assertEqual(RetainedObservation.objects.count(), 1)
        self.assertFalse(Review.objects.exists())
        self.assertFalse(RetainedMessage.objects.exists())
        self.sync(fetched(native='good', rfc='<good>'))
        before = list(Review.objects.values()), list(Candidate.objects.values())
        self.sync(fetched(native='good', rfc='<changed>', body='Acme Robotics changed'))
        self.assertTrue(RetainedMessage.objects.get().has_conflict)
        self.assertEqual(before, (list(Review.objects.values()), list(Candidate.objects.values())))

    def test_retention_review_and_projection_roll_back_together(self):
        with patch('email_sync.sync_service._project_message', side_effect=RuntimeError('projection failure')), self.assertRaises(RuntimeError):
            self.sync(fetched())
        for model in (RetainedMessage, RetainedObservation, RetentionKey, Review, Candidate, AccountMatch, Discovery):
            self.assertFalse(model.objects.exists(), model)
        self.account.refresh_from_db()
        self.assertIsNone(self.account.last_synced_at)
        self.sync(fetched())
        self.assertEqual(Review.objects.count(), 1)

    def test_existing_dismissed_legacy_projection_not_review_authority(self):
        discovery = Discovery.objects.create(account=self.account, message_id='<rfc@example.test>', status='dismissed')
        before = list(Discovery.objects.values())
        self.sync(fetched())
        self.assertEqual(before, list(Discovery.objects.values()))
        self.assertEqual(Review.objects.get().initial_classification, 'match')
        self.assertEqual(Candidate.objects.get().application_id, self.app.pk)
        self.assertFalse(discovery.candidate_applications.exists())
        self.assertFalse(ApplicationMessage.objects.exists())

    def test_other_providers_do_not_create_canonical_reviews(self):
        for provider in ('outlook', 'imap'):
            # Synthetic unbound compatibility account, no provider I/O.
            from email_sync.models import EmailAccount
            account = EmailAccount.objects.create(workspace=self.ws, provider=provider, email='fixture@example.test')
            self.sync(fetched(), account=account)
        self.assertFalse(Review.objects.exists())
        self.assertFalse(RetainedMessage.objects.exists())

    def test_ambiguous_sync_snapshot_survives_new_single_match(self):
        other = Application.objects.create(workspace=self.ws, section='applications',
            company=self.app.company, role_label=self.app.role_label)
        message = fetched()
        self.sync(message)
        before = list(Review.objects.values()), list(Candidate.objects.values()), list(Discovery.objects.values())
        other.company = 'Unrelated'
        other.role_label = 'Unrelated'
        other.save()
        # Fresh observation, same canonical source: exercise ensure replay rather
        # than the existing retention-key changed-payload conflict short circuit.
        self.sync(fetched())
        self.assertFalse(RetainedMessage.objects.get().has_conflict)
        self.assertEqual(before, (list(Review.objects.values()), list(Candidate.objects.values()), list(Discovery.objects.values())))
        self.assertEqual(Review.objects.get().initial_classification, 'ambiguous')
        self.assertFalse(ApplicationMessage.objects.exists())

    def test_snapshot_failure_rolls_back_retention_before_legacy_projection(self):
        with patch('applications.retained_reviews.RetainedApplicationReviewCandidate.objects.create',
                   side_effect=RuntimeError('candidate failure')), self.assertRaises(RuntimeError):
            self.sync(fetched())
        for model in (RetainedMessage, RetainedObservation, RetentionKey, Review, Candidate, AccountMatch, Discovery):
            self.assertFalse(model.objects.exists(), model)
        self.sync(fetched())
        self.assertEqual(Candidate.objects.count(), 1)
