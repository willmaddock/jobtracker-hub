"""Atomic review creation; synthetic sources and isolated databases only."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Barrier, Event, local
from unittest.mock import patch
import uuid

from django.apps import apps
from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError as ModelValidationError
from django.db import connection, connections, IntegrityError, OperationalError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.test import APIClient, APIRequestFactory

from applications.creation import create_attempt
from applications.message_relationships import attach_message
from applications.models import (Application, ApplicationMessage, Override, StatusHistory,
    RetainedApplicationReview as Review, RetainedApplicationReviewCandidate as Candidate,
    RetainedApplicationReviewDisposition as Disposition, RetainedReviewCreationResult as Result)
from applications.retained_reviews import set_review_dismissal, attach_review
from applications.tests.test_retained_reviews import ReviewFixtures
from core.models import ApplicationRequestIntent as Intent
from core.lifecycle import set_trash
from documents.models import Category, CategoryMembership, Document
from email_sync.models import EmailAccount, Discovery, GmailCredential, AccountMatch, ThreadIdentifier
from postings.models import JobPosting


class CreateFixtures(ReviewFixtures):
    def setUp(self):
        super().setUp()
        self.review, _ = self.ensure()
        self.body = {'company': 'Explicit company'}
        self.key = uuid.uuid4().hex

    def endpoint(self, review=None, ws=None):
        return self.review_url(review or self.review, ws) + 'create-application/'

    def send(self, body=None, key=None, review=None, ws=None):
        return self.client.post(self.endpoint(review, ws), self.body if body is None else body,
            format='json', HTTP_IDEMPOTENCY_KEY=key or self.key)

    def service(self, key=None, body=None):
        body = self.body if body is None else body
        return create_attempt(actor=self.user, workspace=self.ws, key=key or self.key,
            supplied={k: v for k, v in body.items() if k != 'challenge'},
            values={k: v for k, v in body.items() if k != 'challenge'},
            review_id=self.review.pk, challenge=body.get('challenge'))

    def dismiss(self, dismissed=True, revision=0):
        return set_review_dismissal(actor=self.user, workspace=self.ws, review_id=self.review.pk,
                                   dismissed=dismissed, expected_revision=revision)

    def fresh_review(self, ids=()):
        data = deepcopy(self.data)
        tag = uuid.uuid4().hex
        data['source']['value'] = tag
        message = self.retain(tag, data)
        return self.ensure(list(ids), retained_message_id=message.pk,
                           observation_id=message.observations.get().pk)[0]

    def snapshot(self):
        return {m._meta.label: list(m.objects.order_by('pk').values())
                for m in apps.get_models(include_auto_created=True)}

    def confirm(self, body=None, key=None, review=None):
        body = self.body if body is None else body
        warning = self.send(body, key, review)
        self.assertEqual((warning.status_code, warning.data['code']), (409, 'new_attempt_confirmation_required'))
        return self.send({**body, 'challenge': warning.data['challenge']}, key, review)


class ReviewCreateTests(CreateFixtures, TestCase):
    def test_continuation_intent_persistence(self):
        before = self.snapshot()
        response = self.send({**self.body, 'challenge': 'arbitrary'})
        self.assertEqual((response.status_code, response.data['code']), (409, 'invalid_challenge'))
        self.assertEqual(before, self.snapshot())
        self.assertFalse(Intent.objects.exists())
        self.attach()
        count = Intent.objects.count()
        warning = self.send()
        self.assertEqual(warning.data['code'], 'new_attempt_confirmation_required')
        self.assertEqual(Intent.objects.count(), count + 1)
        intent = Intent.objects.get(key=self.key)
        self.assertFalse(intent.completed)
        self.assertEqual(intent.challenge_token, warning.data['challenge'])
        self.assertTrue(intent.challenge_revision)
        self.assertIsNotNone(intent.challenge_expires_at)
        before = self.snapshot()
        for token, key in (('wrong', self.key), (warning.data['challenge'], uuid.uuid4().hex)):
            response = self.send({**self.body, 'challenge': token}, key)
            self.assertEqual((response.status_code, response.data['code']), (409, 'invalid_challenge'))
            self.assertEqual(before, self.snapshot())
        response = self.send({**self.body, 'company': 'Changed', 'challenge': 'wrong'})
        self.assertEqual(response.data['code'], 'idempotency_key_reused')
        self.assertEqual(before, self.snapshot())
        created = self.send({**self.body, 'challenge': warning.data['challenge']})
        self.assertEqual(created.status_code, 201)
        before = self.snapshot()
        replay = self.send({**self.body, 'challenge': 'wrong'})
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.data, created.data)
        self.assertEqual(before, self.snapshot())

    def test_zero_one_many_explicit_fields_and_provenance(self):
        other = self.application(self.ws)
        category = Category.objects.create(workspace=self.ws, name='Archived', section='misc', archived=True)
        for count, ids in enumerate(([], [self.app.pk], [self.app.pk, other.pk])):
            review = self.fresh_review(ids)
            body = {'company': f' Explicit {count} ', 'role_label': ' New role ',
                    'status': 'interviewing', 'category_id': category.pk}
            if ids:
                body['candidate_id'] = review.candidates.first().pk
            before = list(Review.objects.values()), list(Candidate.objects.values())
            response = self.send(body, uuid.uuid4().hex, review)
            self.assertEqual(response.status_code, 201, response.data)
            row = Result.objects.get(pk=response.data['id'])
            app = row.application_message.application
            self.assertEqual((app.company, app.role_label, app.section), (f'Explicit {count}', 'New role', 'applications'))
            self.assertEqual(app.override.manual_status, 'interviewing')
            self.assertEqual(app.status_history.get().source, 'review_create')
            self.assertEqual(app.category_membership.category, category)
            self.assertEqual(app.category_revision, 1)
            self.assertEqual(row.input_snapshot, {**body, 'company': f'Explicit {count}', 'role_label': 'New role'})
            self.assertEqual(row.request_intent.application, app)
            self.assertTrue(row.request_intent.completed)
            self.assertEqual(row.application_message.retained_message_id, review.retained_message_id)
            self.assertEqual(before, (list(Review.objects.values()), list(Candidate.objects.values())))
        self.assertEqual(Result.objects.count(), 3)
        self.assertEqual(ApplicationMessage.objects.count(), 3)
        self.assertFalse(Disposition.objects.exists())

    def test_omitted_blank_null_snapshot_and_no_inference(self):
        variants = ({'company': 'New'}, {'company': 'New', 'role_label': '', 'status': ''},
                    {'company': 'New', 'category_id': None, 'candidate_id': None})
        for index, body in enumerate(variants):
            body = {**body, 'company': f'New {index}'}
            response = self.send(body, uuid.uuid4().hex, self.fresh_review())
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.data['input_snapshot'], body)
            self.assertEqual(response.data['snapshot_version'], 1)
            app = Application.objects.get(pk=response.data['application']['id'])
            self.assertEqual((app.role_label, app.status), ('', 'unknown'))
            self.assertIsNone(app.first_activity)
            self.assertIsNone(app.last_activity)
            self.assertIsNone(app.automatic_date_applied)
            self.assertIsNone(app.first_activity_date)
            self.assertFalse(Override.objects.filter(application=app).exists())
            self.assertFalse(StatusHistory.objects.filter(application=app).exists())
            self.assertFalse(CategoryMembership.objects.filter(application=app).exists())
        self.assertFalse(Document.objects.exists())

    def test_strict_payload_key_methods_auth_csrf_and_suffix(self):
        url = self.endpoint()
        self.assertEqual(APIClient().post(url, self.body, format='json').status_code, 401)
        csrf = APIClient(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        self.assertEqual(csrf.post(url, self.body, format='json').status_code, 403)
        invalid = [{}, [], None, {'company': ''}, {'company': ' '}, {'company': 'x' * 256}]
        for field in ('company', 'role_label', 'status'):
            invalid += [{**self.body, field: v} for v in (None, True, 12, 1.2, [], {})]
        for field in ('category_id', 'candidate_id'):
            invalid += [{**self.body, field: v} for v in (True, False, '1', 1.0, 0, -1, 2**63, [], {})]
        invalid += [{**self.body, field: 1} for field in ('id', 'section', 'workspace', 'owner',
                    'retained_message_id', 'expected_revision', 'created_at', 'portable_id', 'extra')]
        invalid += [{**self.body, 'challenge': v} for v in ('', 'é', 'x' * 65, None, True, 1, [])]
        invalid.append({**self.body, 'status': 'invented'})
        for body in invalid:
            response = self.client.post(url, body, format='json', HTTP_IDEMPOTENCY_KEY=self.key)
            self.assertEqual(response.status_code, 400, (body, response.data))
        self.assertEqual(self.client.post(url, '{', content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(url, self.body, format='json').status_code, 400)
        for key in ('short', 'a' * 129, 'x' * 15 + '/', 'é' * 16):
            self.assertEqual(self.send(key=key).status_code, 400)
        for method in ('get', 'put', 'patch', 'delete'):
            self.assertEqual(getattr(self.client, method)(url).status_code, 405)
        self.assertFalse(Intent.objects.exists())
        self.assertEqual(self.client.post(url.rstrip('/') + '.json', self.body, format='json',
                                        HTTP_IDEMPOTENCY_KEY=self.key).status_code, 201)

    def test_scope_missing_and_corrupt_references(self):
        for ws in (self.ws_b, self.ws_c):
            self.assertEqual(self.send(ws=ws).status_code, 404)
        for field in ('candidate_id', 'category_id'):
            self.assertEqual(self.send({**self.body, field: 9223372036854775807}).status_code, 404)
        category = Category.objects.create(workspace=self.ws_b, name='Foreign', section='misc')
        self.assertEqual(self.send({**self.body, 'category_id': category.pk}).status_code, 404)
        foreign_candidate = self.fresh_review([self.app.pk]).candidates.get()
        self.assertEqual(self.send({**self.body, 'candidate_id': foreign_candidate.pk}).status_code, 404)
        observation = self.review.originating_observation
        mutations = [(Review, self.review.pk, 'workspace_id', self.ws_b.pk),
            (type(self.message), self.message.pk, 'workspace_id', self.ws_b.pk),
            (type(self.mailbox), self.mailbox.pk, 'workspace_id', self.ws_b.pk),
            (type(observation), observation.pk, 'message_id', None),
            (type(observation), observation.pk, 'mailbox_id', None),
            (type(observation.key), observation.key_id, 'workspace_id', self.ws_b.pk)]
        for model, pk, field, value in mutations:
            qs = model.objects.filter(pk=pk)
            original = qs.values_list(field, flat=True).get()
            qs.update(**{field: value})
            self.assertEqual(self.send().status_code, 404, (model, field))
            qs.update(**{field: original})
        self.assertFalse(Result.objects.exists())
        self.assertFalse(Intent.objects.exists())

    def test_candidate_null_trashed_and_corrupt_identity(self):
        candidate = self.review.candidates.get()
        body = {**self.body, 'candidate_id': candidate.pk}
        Candidate.objects.filter(pk=candidate.pk).update(application_portable_id=uuid.uuid4())
        self.assertEqual(self.send(body).status_code, 404)
        Candidate.objects.filter(pk=candidate.pk).update(application_portable_id=self.app.portable_id)
        set_trash(actor=self.user, workspace=self.ws, kind='applications', pk=self.app.pk, trashed=True, expected_revision=0)
        self.assertEqual(self.send(body).status_code, 201)
        # Historical candidate may retain only portable provenance after removal.
        candidate2 = self.fresh_review([self.app.pk]).candidates.get()
        Candidate.objects.filter(pk=candidate2.pk).update(application=None)
        response = self.send({**self.body, 'company': 'Another', 'candidate_id': candidate2.pk},
                             uuid.uuid4().hex, candidate2.review)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['application']['role_label'], '')

    def test_category_trash_rejection_and_default_status(self):
        category = Category.objects.create(workspace=self.ws, name='Gone', section='misc', trashed_at=timezone.now())
        response = self.send({**self.body, 'category_id': category.pk})
        self.assertEqual((response.status_code, response.data['code']), (409, 'resource_trashed'))
        self.assertFalse(Intent.objects.exists())

    def test_completed_replay_skips_all_writers_and_mutable_admission(self):
        from applications import review_creation
        first = self.send()
        self.assertEqual(first.status_code, 201, first.data)
        app = Application.objects.get(pk=first.data['application']['id'])
        before = list(Result.objects.values())
        self.dismiss()
        type(self.message).objects.filter(pk=self.message.pk).update(has_conflict=True)
        set_trash(actor=self.user, workspace=self.ws, kind='applications', pk=app.pk, trashed=True, expected_revision=0)
        with patch.object(Application.objects, 'create', side_effect=AssertionError('allocate on replay')), \
             patch('applications.message_relationships.attach_message', side_effect=AssertionError('attach on replay')), \
             patch.object(Result.objects, 'create', side_effect=AssertionError('result on replay')), \
             patch.object(review_creation, 'admit', side_effect=AssertionError('admit on replay')):
            replay = self.send()
            self.assertEqual(replay.status_code, 200)
            self.assertEqual(replay.data['id'], first.data['id'])
            self.assertEqual(replay.data['created_at'], first.data['created_at'])
            self.assertTrue(replay.data['application']['is_trashed'])
            self.assertEqual(replay.data['disposition']['state'], 'dismissed')
        set_trash(actor=self.user, workspace=self.ws, kind='applications', pk=app.pk, trashed=False, expected_revision=1)
        self.dismiss(False, 1)
        self.assertFalse(self.send().data['application']['is_trashed'])
        self.assertEqual(before, list(Result.objects.values()))
        self.assertEqual(ApplicationMessage.objects.count(), 1)

    def test_digest_omission_null_order_review_and_kind(self):
        self.assertEqual(self.send().status_code, 201)
        for body in ({**self.body, 'role_label': ''}, {**self.body, 'candidate_id': None},
                     {**self.body, 'category_id': None}, {'company': 'Changed'}):
            self.assertEqual(self.send(body).data['code'], 'idempotency_key_reused')
        self.assertEqual(self.send(review=self.fresh_review()).data['code'], 'idempotency_key_reused')
        response = self.client.post(f'/api/workspaces/{self.ws.pk}/applications/', self.body,
                                    format='json', HTTP_IDEMPOTENCY_KEY=self.key)
        self.assertEqual(response.data['code'], 'idempotency_key_reused')
        body = {'company': 'Order', 'role_label': 'Role', 'candidate_id': None}
        review, key = self.fresh_review(), uuid.uuid4().hex
        self.assertEqual(self.send(body, key, review).status_code, 201)
        self.assertEqual(self.send(dict(reversed(list(body.items()))), key, review).status_code, 200)

    def test_new_work_dismissal_conflict_and_corrupt_pair_fail_closed(self):
        self.dismiss()
        self.assertEqual(self.send().data['code'], 'review_dismissed')
        self.dismiss(False, 1)
        type(self.message).objects.filter(pk=self.message.pk).update(has_conflict=True)
        self.assertEqual(self.send().data['code'], 'retained_source_ineligible')
        type(self.message).objects.filter(pk=self.message.pk).update(has_conflict=False)
        self.attach()
        ApplicationMessage.objects.update(workspace=self.ws_b)
        self.assertEqual(self.send().status_code, 404)
        self.assertFalse(Result.objects.exists())
        self.assertFalse(Intent.objects.exists())

    def test_distinct_warning_signals_and_confirmed_new_attempt(self):
        duplicate_body = {'company': ' same ', 'role_label': 'Engineer'}
        warning = self.send(duplicate_body)
        self.assertEqual(len(warning.data['candidates']), 1)
        self.assertEqual(warning.data['source_relationships'], [])
        self.assertEqual(warning.data['prior_creation_results'], [])
        self.attach()
        key = uuid.uuid4().hex
        warning = self.send(key=key)
        self.assertEqual(warning.data['candidates'], [])
        self.assertEqual(len(warning.data['source_relationships']), 1)
        self.assertEqual(warning.data['prior_creation_results'], [])
        first = self.send({**self.body, 'challenge': warning.data['challenge']}, key)
        self.assertEqual(first.status_code, 201)
        other_body, key = {'company': 'Different labels'}, uuid.uuid4().hex
        warning = self.send(other_body, key)
        self.assertEqual(warning.data['candidates'], [])
        self.assertEqual(len(warning.data['source_relationships']), 2)
        self.assertEqual(len(warning.data['prior_creation_results']), 1)
        second = self.send({**other_body, 'challenge': warning.data['challenge']}, key)
        self.assertEqual(second.status_code, 201)
        self.assertNotEqual(first.data['application']['id'], second.data['application']['id'])
        self.assertEqual(Result.objects.count(), 2)
        self.assertEqual(ApplicationMessage.objects.count(), 3)
        self.assertEqual(self.send({**other_body, 'challenge': warning.data['challenge']}, key).status_code, 200)

    def test_challenge_invalidation_expiry_renewal_and_unrelated_candidate_labels(self):
        self.attach()
        category = Category.objects.create(workspace=self.ws, name='Group', section='misc')
        body = {**self.body, 'category_id': category.pk}
        warning = self.send(body)
        token = warning.data['challenge']
        self.dismiss(); self.dismiss(False, 1)
        self.assertEqual(self.send({**body, 'challenge': token}).data['code'], 'stale_challenge')
        mutations = [lambda: self.attach_extra(),
                     lambda: Category.objects.filter(pk=category.pk).update(revision=1),
                     lambda: Application.objects.filter(pk=self.app.pk).update(trashed_at=timezone.now(), lifecycle_revision=1),
                     lambda: Application.objects.create(workspace=self.ws, company=body['company'], section='applications')]
        for mutate in mutations:
            token = self.send(body).data['challenge']
            mutate()
            self.assertEqual(self.send({**body, 'challenge': token}).data['code'], 'stale_challenge')
        token = self.send(body).data['challenge']
        self.assertEqual(self.confirm({'company': 'Intervening'}, uuid.uuid4().hex).status_code, 201)
        self.assertEqual(self.send({**body, 'challenge': token}).data['code'], 'stale_challenge')
        token = self.send(body).data['challenge']
        Intent.objects.filter(key=self.key).update(challenge_expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.send({**body, 'challenge': token}).data['code'], 'challenge_expired')
        renewed = self.send(body).data['challenge']
        self.assertEqual(self.send({**body, 'challenge': token}).data['code'], 'invalid_challenge')
        self.assertEqual(self.send({**body, 'company': 'Changed', 'challenge': renewed}).data['code'], 'idempotency_key_reused')
        self.assertEqual(self.send({**body, 'challenge': renewed}).status_code, 201)

    def attach_extra(self):
        other = self.application(self.ws)
        return attach_message(actor=self.user, workspace=self.ws, application_id=other.pk, retained_message_id=self.message.pk)

    def test_unrelated_candidate_label_does_not_stale_confirmation(self):
        other = self.application(self.ws)
        review = self.fresh_review([other.pk])
        attach_message(actor=self.user, workspace=self.ws, application_id=self.app.pk, retained_message_id=review.retained_message_id)
        body = {**self.body, 'candidate_id': review.candidates.get().pk}
        token = self.send(body, review=review).data['challenge']
        other.company = 'Changed historical suggestion'
        other.save()
        response = self.send({**body, 'challenge': token}, review=review)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['application']['company'], self.body['company'])

    def test_result_model_admin_uniqueness_and_missing_result_integrity(self):
        self.send()
        row = Result.objects.get()
        with self.assertRaises(ModelValidationError):
            row.save()
        with self.assertRaises(ModelValidationError):
            row.delete()
        with self.assertRaises(ProtectedError):
            Intent.objects.filter(pk=row.request_intent_id).delete()
        values = {f.name: getattr(row, f.name) for f in Result._meta.fields if f.name not in ('id', 'created_at')}
        with self.assertRaises(IntegrityError), transaction.atomic():
            Result.objects.bulk_create([Result(**values)])
        model_admin = admin.site._registry[Result]
        request = APIRequestFactory().get('/')
        request.user = self.user
        for method in ('has_add_permission', 'has_change_permission', 'has_delete_permission'):
            self.assertFalse(getattr(model_admin, method)(request))
        self.assertFalse(model_admin.get_actions(request))
        self.assertEqual(set(model_admin.get_readonly_fields(request)), {f.name for f in Result._meta.fields})
        # Privileged corruption fixture; never a product deletion path.
        Result.objects.all().delete()
        before = self.snapshot()
        response = self.send()
        self.assertEqual((response.status_code, response.data['code']), (500, 'creation_result_inconsistent'))
        self.assertEqual(before, self.snapshot())

    def test_negative_scope_preserves_all_other_tables(self):
        account = EmailAccount.objects.create(workspace=self.ws, email='fixture@example.test', provider='gmail')
        GmailCredential.objects.create(account=account, access_token='synthetic', refresh_token='synthetic')
        discovery = Discovery.objects.create(account=account, message_id='legacy', status='accepted')
        discovery.candidate_applications.add(self.app)
        AccountMatch.objects.create(account=account, application=self.app, message_id='legacy')
        ThreadIdentifier.objects.create(application=self.app, message_id='<legacy>')
        JobPosting.objects.create(workspace=self.ws, account=account, dedupe_key='preserve')
        allowed = {Application, ApplicationMessage, Result, Intent, Override, StatusHistory, CategoryMembership}
        others = [m for m in apps.get_models(include_auto_created=True) if m not in allowed]
        before = [list(m.objects.order_by('pk').values()) for m in others]
        self.assertEqual(self.send().status_code, 201)
        self.assertEqual(before, [list(m.objects.order_by('pk').values()) for m in others])
        self.assertFalse(Document.objects.exists())

    def test_real_write_failures_roll_back_whole_graph_and_pending_state(self):
        from applications import review_creation
        category = Category.objects.create(workspace=self.ws, name='Group', section='misc')
        body = {**self.body, 'status': 'applied', 'category_id': category.pk}
        def after(real):
            def fail(*args, **kwargs):
                real(*args, **kwargs)
                raise RuntimeError('after real write')
            return fail
        app_create, result_create = Application.objects.create, Result.objects.create
        intent_save = Intent.save
        def fail_completion(instance, *args, **kwargs):
            intent_save(instance, *args, **kwargs)
            if instance.completed:
                raise RuntimeError('after actual completion')
        cases = [lambda: patch.object(Application.objects, 'create', side_effect=after(app_create)),
                 lambda: patch('applications.message_relationships.attach_message', side_effect=after(attach_message)),
                 lambda: patch.object(ApplicationMessage, 'save', new=after(ApplicationMessage.save)),
                 lambda: patch.object(Result.objects, 'create', side_effect=RuntimeError('before result')),
                 lambda: patch.object(Result.objects, 'create', side_effect=after(result_create)),
                 lambda: patch.object(Intent, 'save', new=fail_completion),
                 lambda: patch.object(review_creation, 'result_data', side_effect=RuntimeError('outcome'))]
        for pending in (False, True):
            if pending:
                self.attach()
                token = self.send(body).data['challenge']
                body = {**body, 'challenge': token}
            for make_patch in cases:
                before = self.snapshot()
                with make_patch(), self.assertRaises(RuntimeError):
                    self.send(body)
                self.assertEqual(before, self.snapshot())
        self.assertEqual(self.send(body).status_code, 201)

    def test_service_boundary_rejects_unauthorized_or_inconsistent_input(self):
        base = dict(actor=self.user, workspace=self.ws, key=self.key, supplied=self.body,
                    values=self.body, review_id=self.review.pk)
        for changes, error in (({"actor": AnonymousUser()}, NotFound),
                ({"actor": self.other}, NotFound), ({"key": True}, ValidationError),
                ({"challenge": True}, ValidationError), ({"challenge": "é"}, ValidationError),
                ({"values": {"company": "Different"}}, ValidationError),
                ({"review_id": True}, ValidationError), ({"posting_id": 1}, ValidationError)):
            with self.assertRaises(error):
                create_attempt(**{**base, **changes})
        self.assertFalse(Intent.objects.exists())
        self.assertFalse(Result.objects.exists())

    def test_result_scope_snapshot_and_identity_validation(self):
        self.send()
        original = Result.objects.get()
        fields = {f.name: getattr(original, f.name) for f in Result._meta.fields
                  if f.name not in ('id', 'created_at')}
        bad_snapshots = ({}, [], {"company": True}, {"company": " Untrimmed "},
                         {"company": "New", "challenge": "secret"}, {"company": "New", "category_id": True})
        for snapshot in bad_snapshots:
            with self.assertRaises(ModelValidationError):
                Result(**{**fields, "input_snapshot": snapshot}).save()
        wrong = self.fresh_review([self.app.pk])
        for changes in ({"snapshot_version": 2}, {"review": wrong},
                        {"candidate": wrong.candidates.get()}):
            with self.assertRaises(ModelValidationError):
                Result(**{**fields, **changes}).save()
        original.review = wrong
        with self.assertRaises(ModelValidationError):
            original.save()
        Intent.objects.filter(pk=original.request_intent_id).update(result_portable_id=uuid.uuid4())
        before = self.snapshot()
        response = self.send()
        self.assertEqual((response.status_code, response.data['code']), (500, 'creation_result_inconsistent'))
        self.assertEqual(before, self.snapshot())

    def test_key_namespace_and_challenge_cannot_cross_requests(self):
        manual_key = uuid.uuid4().hex
        response = self.client.post(f'/api/workspaces/{self.ws.pk}/applications/', {"company": "Manual"},
                                   format='json', HTTP_IDEMPOTENCY_KEY=manual_key)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.send(key=manual_key).data['code'], 'idempotency_key_reused')
        self.attach()
        token = self.send().data['challenge']
        body = {**self.body, 'challenge': token}
        self.assertEqual(self.send(body, uuid.uuid4().hex).data['code'], 'invalid_challenge')
        self.assertEqual(self.send(body, review=self.fresh_review()).data['code'], 'idempotency_key_reused')
        # This owned Workspace has no intent for the key: continuation rejection
        # now precedes review lookup and must not leave any durable state.
        before = self.snapshot()
        response = self.send(body, ws=self.ws_b)
        self.assertEqual((response.status_code, response.data['code']), (409, 'invalid_challenge'))
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.send(ws=self.ws_b).status_code, 404)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.send(body).status_code, 404)
        self.assertFalse(Result.objects.exists())

    def test_detail_pagination_and_list_stays_lightweight(self):
        for n in range(51):
            body, key = {'company': f'Created {n}'}, uuid.uuid4().hex
            response = self.confirm(body, key) if n else self.send(body, key)
            self.assertEqual(response.status_code, 201)
        first = self.detail(self.review)['creation_results']
        self.assertEqual(len(first['results']), 50)
        self.assertIsNotNone(first['next_after'])
        second = self.client.get(self.review_url(self.review), {'creation_results_after': first['next_after']})
        self.assertEqual(len(second.data['creation_results']['results']), 1)
        self.assertIsNone(second.data['creation_results']['next_after'])
        self.assertNotIn('creation_results', self.client.get(self.review_url()).data['results'][0])
        for cursor in ('-1', 'x', '1.0', str(2**63), '١'):
            self.assertEqual(self.client.get(self.review_url(self.review), {'creation_results_after': cursor}).status_code, 400)
        self.assertEqual(self.client.get(self.review_url(self.review, self.ws_b)).status_code, 404)
        self.assertEqual(self.detail(self.fresh_review())['creation_results']['results'], [])


class ReviewCreateConcurrencyTests(CreateFixtures, TransactionTestCase):
    def test_post_commit_response_loss_replays_complete_result(self):
        with patch('applications.creation.Response', side_effect=RuntimeError('response lost')):
            with self.assertRaises(RuntimeError):
                self.service()
        self.assertTrue(Intent.objects.get().completed)
        row = Result.objects.get()
        self.assertEqual(ApplicationMessage.objects.count(), 1)
        self.assertEqual(self.service().data['id'], row.pk)
        self.assertEqual(Result.objects.count(), 1)

    def test_api_creation_busy_covers_admission_and_gate(self):
        for target in ('applications.creation.lock_workspace', 'core.workspace_scope.get_object_or_404'):
            before = self.snapshot()
            with patch(target, side_effect=OperationalError('database is locked')):
                response = self.send()
            self.assertEqual((response.status_code, response.data['code']), (503, 'creation_busy'))
            self.assertEqual(before, self.snapshot())

    def race(self, operations):
        barrier = Barrier(len(operations))
        def run(operation):
            connections.close_all()
            try:
                barrier.wait(10)
                return operation().status_code
            except OperationalError as exc:
                if connection.vendor != 'sqlite' or 'locked' not in str(exc).lower():
                    raise
                return 503
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            return list(pool.map(run, operations))

    def test_same_key_and_different_key_races(self):
        outcomes = self.race([self.service, self.service])
        self.assertTrue(set(outcomes) <= {200, 201, 503})
        self.assertLessEqual(outcomes.count(201), 1)
        self.assertIn(self.service().status_code, (200, 201))
        self.assertEqual(Result.objects.count(), 1)
        # New review with a new source, different requests still serialize repeat context.
        self.review = self.fresh_review()
        self.body = {'company': 'Race new source'}
        keys = [uuid.uuid4().hex, uuid.uuid4().hex]
        outcomes = self.race([lambda: self.service(keys[0]), lambda: self.service(keys[1])])
        self.assertTrue(set(outcomes) <= {201, 409, 503})
        self.assertLessEqual(outcomes.count(201), 1)
        for key in keys:
            self.assertIn(self.service(key).status_code, (200, 201, 409))
        self.assertEqual(Result.objects.filter(review=self.review).count(), 1)

    def ordered(self, winner_action, loser_action):
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
        def run(operation, winner):
            connections.close_all(); worker.winner = winner
            try:
                result = operation()
                return result.status_code if hasattr(result, 'status_code') else 200
            except OperationalError as exc:
                if connection.vendor != 'sqlite' or 'locked' not in str(exc).lower():
                    raise
                return 503
            except APIException as exc:
                return exc.status_code
            finally:
                connections.close_all()
        with patch('applications.creation.lock_workspace', side_effect=gate), \
             patch('applications.retained_reviews.lock_workspace', side_effect=gate):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(run, winner_action, True)
                try:
                    self.assertTrue(acquired.wait(10))
                    second = pool.submit(run, loser_action, False)
                    self.assertTrue(attempted.wait(10))
                finally:
                    release.set()
                return first.result(10), second.result(10)

    def test_create_wins_dismiss_race(self):
        first, second = self.ordered(self.service, self.dismiss)
        self.assertEqual(first, 201)
        self.assertIn(second, (200, 503))
        if second == 503:
            self.dismiss()
        self.assertEqual(self.service().status_code, 200)
        self.assertEqual(Result.objects.count(), 1)
        self.assertEqual(ApplicationMessage.objects.count(), 1)

    def test_dismiss_wins_create_race(self):
        first, second = self.ordered(self.dismiss, self.service)
        self.assertEqual(first, 200)
        self.assertIn(second, (409, 503))
        self.assertEqual(self.send().data['code'], 'review_dismissed')
        self.assertFalse(Result.objects.exists())
        self.assertFalse(ApplicationMessage.objects.exists())

    def test_attach_wins_create_requires_confirmation(self):
        operation = lambda: attach_review(actor=self.user, workspace=self.ws,
            review_id=self.review.pk, application_id=self.app.pk)
        first, second = self.ordered(operation, self.service)
        self.assertEqual(first, 200)
        self.assertIn(second, (409, 503))
        self.assertEqual(self.service().data['code'], 'new_attempt_confirmation_required')
        self.assertFalse(Result.objects.exists())

    def test_create_wins_attach_preserves_both_relationships(self):
        operation = lambda: attach_review(actor=self.user, workspace=self.ws,
            review_id=self.review.pk, application_id=self.app.pk)
        first, second = self.ordered(self.service, operation)
        self.assertEqual(first, 201)
        self.assertIn(second, (200, 503))
        if second == 503:
            operation()
        self.assertEqual(Result.objects.count(), 1)
        self.assertEqual(ApplicationMessage.objects.count(), 2)

    def test_different_intent_confirmations_stale_after_first_commit(self):
        self.attach()
        keys = [uuid.uuid4().hex, uuid.uuid4().hex]
        bodies = [{**self.body, 'challenge': self.service(key).data['challenge']} for key in keys]
        first, second = self.ordered(lambda: self.service(keys[0], bodies[0]),
                                     lambda: self.service(keys[1], bodies[1]))
        self.assertEqual(first, 201)
        self.assertIn(second, (409, 503))
        self.assertEqual(self.service(keys[1], bodies[1]).data['code'], 'stale_challenge')
        self.assertEqual(Result.objects.count(), 1)
        self.assertEqual(self.confirm(key=keys[1]).status_code, 201)
        self.assertEqual(Result.objects.count(), 2)

    def test_competing_confirmations_and_renewal(self):
        self.attach()
        token = self.service().data['challenge']
        body = {**self.body, 'challenge': token}
        outcomes = self.race([lambda: self.service(body=body), lambda: self.service(body=body)])
        self.assertTrue(set(outcomes) <= {200, 201, 503})
        self.assertLessEqual(outcomes.count(201), 1)
        self.assertIn(self.service(body=body).status_code, (200, 201))
        self.assertEqual(Result.objects.count(), 1)
        # Renewal wins the gate: old continuation must never create another effect.
        self.key = uuid.uuid4().hex
        token = self.service().data['challenge']
        body = {**self.body, 'challenge': token}
        first, second = self.ordered(self.service, lambda: self.service(body=body))
        self.assertEqual(first, 409)
        self.assertIn(second, (409, 503))
        self.assertEqual(self.service(body=body).data['code'], 'invalid_challenge')
        self.assertEqual(Result.objects.count(), 1)
