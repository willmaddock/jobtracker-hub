"""Actual response-save transactions, revoked cookies and stable-row contention."""
from copy import deepcopy
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest import mock
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.db import OperationalError, close_old_connections, connection, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone
from datetime import timedelta
from gateway import session_context as ctx, session_lineage as lineage
from gateway.models import GatewaySessionLineage


@override_settings(JTH_GATEWAY=True, ROOT_URLCONF='gateway.tests_session_context', MFA_REQUIRED=False)
class LineageTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        for name in ('A', 'B'):
            get_user_model().objects.create_user(username=name, password='synthetic-only')
        self.client = Client(enforce_csrf_checks=True)
        self.binding = self.bootstrap(self.client)

    def bootstrap(self, client):
        root = client.get('/')
        self.assertEqual(root.status_code, 200, root.content[:200])
        return json.loads(re.search(r'window.JTH_GATEWAY_PAGE = (\{.*?\});', root.content.decode()).group(1))['binding']

    def post(self, client, binding, username='A'):
        csrf = client.get('/api/auth/csrf').json()['csrfToken']
        return client.post('/api/auth/login', json.dumps({'username':username,'password':'synthetic-only'}),
                           content_type='application/json', HTTP_X_JTH_CONTEXT=binding, HTTP_X_CSRFTOKEN=csrf)

    def row(self):
        return GatewaySessionLineage.objects.get(pk=lineage.cookie_id(type('Request', (), {'COOKIES':{k:v.value for k,v in self.client.cookies.items()}})()))

    def test_session_and_authority_commit_on_same_connection_and_transaction(self):
        writes, committed = [], []
        def inspect(execute, sql, params, many, context):
            if sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) and any(t in sql for t in ('django_session', 'gateway_gatewaysessionlineage')):
                writes.append((sql, context['connection'].alias, context['connection'].in_atomic_block))
                if not committed:
                    transaction.on_commit(lambda: committed.append((self.row().generation, Session.objects.get(session_key=self.row().session_key).get_decoded()[ctx.KEY])))
            return execute(sql, params, many, context)
        with connection.execute_wrapper(inspect):
            result = self.post(self.client, self.binding)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertTrue(writes)
        self.assertTrue(all(alias == 'default' and atomic for _, alias, atomic in writes), writes)
        self.assertTrue(any('django_session' in sql for sql, _, _ in writes))
        self.assertTrue(any('gateway_gatewaysessionlineage' in sql for sql, _, _ in writes))
        self.assertTrue(committed)
        self.assertTrue(all(g == 1 and mirror['g'] == '1' for g, mirror in committed))
        self.assertFalse(connection.in_atomic_block)

    def assert_rolled_back(self, failure):
        row = self.row()
        before = (row.generation, row.session_key, list(Session.objects.values_list('session_key', flat=True)))
        self.client.raise_request_exception = False
        with failure:
            result = self.post(self.client, self.binding)
        self.assertGreaterEqual(result.status_code, 500)
        self.assertNotIn(settings.SESSION_COOKIE_NAME, result.cookies)
        self.assertNotIn(ctx.cookie_name(), result.cookies)
        row.refresh_from_db()
        self.assertEqual((row.generation, row.session_key, list(Session.objects.values_list('session_key', flat=True))), before)
        self.assertEqual(self.client.get('/api/gateway/context', HTTP_X_JTH_CONTEXT=self.binding).status_code, 204)

    def test_authority_save_failure_rolls_back_native_login_and_session_save(self):
        self.assert_rolled_back(mock.patch.object(GatewaySessionLineage, 'save', side_effect=OperationalError('synthetic authority failure')))

    def test_framework_session_save_failure_rolls_back_authority_and_deletion(self):
        self.assert_rolled_back(mock.patch.object(SessionStore, 'save', side_effect=OperationalError('synthetic session failure')))

    def test_stable_cookie_never_reissued_by_authentication_or_context_checks(self):
        stable = self.client.cookies[ctx.cookie_name()].value
        for name in ('A', 'B', 'A'):
            result = self.post(self.client, self.binding, name)
            self.assertEqual(result.status_code, 200)
            self.assertNotIn(ctx.cookie_name(), result.cookies)
            self.binding = result[ctx.HEADER]
        self.assertEqual(self.client.cookies[ctx.cookie_name()].value, stable)
        result = self.client.get('/api/gateway/context', HTTP_X_JTH_CONTEXT=self.binding)
        self.assertEqual(result.status_code, 204)
        self.assertNotIn(settings.SESSION_COOKIE_NAME, result.cookies)

    def test_delayed_cookie_after_explicit_restart_and_new_login_is_revoked(self):
        a = self.post(self.client, self.binding)
        held_client = Client(enforce_csrf_checks=True)
        held_client.cookies = deepcopy(self.client.cookies)
        held = self.post(held_client, a[ctx.HEADER], 'B')
        self.assertEqual(held.status_code, 200)
        rejected = self.post(self.client, a[ctx.HEADER])
        self.assertEqual((rejected.status_code, rejected.json()['code']), (409, 'gateway_session_obsolete'))
        page = self.client.get('/')
        self.assertEqual(page.status_code, 409)
        recovery = json.loads(re.search(r'window.JTH_GATEWAY_RECOVERY = (\{.*?\});', page.content.decode()).group(1))
        restart = self.client.post('/api/gateway/session/restart', HTTP_X_CSRFTOKEN=recovery['csrf'], HTTP_X_JTH_RECOVERY=recovery['challenge'])
        self.assertEqual(restart.status_code, 204, restart.content)
        fresh_a = self.post(self.client, restart[ctx.HEADER])
        self.assertEqual(fresh_a.status_code, 200)
        current_cookie = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        # Install only the genuinely held Set-Cookie response, exactly as a browser does.
        self.client.cookies.update(held.cookies)
        for token in (held[ctx.HEADER], fresh_a[ctx.HEADER]):
            result = self.client.get('/api/auth/me', HTTP_X_JTH_CONTEXT=token)
            self.assertEqual((result.status_code, result.json()['code']), (409, 'gateway_session_obsolete'))
            self.assertNotIn(settings.SESSION_COOKIE_NAME, result.cookies)
        with override_settings(ROOT_URLCONF='gateway.tests_forms'):
            csrf = self.client.get('/api/auth/csrf').json()['csrfToken']
            form = self.client.post('/app/sign-out/', {'_jth_context':held[ctx.HEADER], 'csrfmiddlewaretoken':csrf})
            self.assertContains(form, 'gateway_session_obsolete', status_code=409)
            self.assertNotIn(settings.SESSION_COOKIE_NAME, form.cookies)
        self.assertFalse(Session.objects.filter(session_key=held_client.cookies[settings.SESSION_COOKIE_NAME].value).exists())
        self.client.cookies[settings.SESSION_COOKIE_NAME] = current_cookie
        result = self.client.get('/api/auth/me', HTTP_X_JTH_CONTEXT=fresh_a[ctx.HEADER])
        self.assertEqual((result.status_code, result.json()['username']), (200, 'A'))

    def test_separate_profiles_and_devices_remain_independent(self):
        other = Client(enforce_csrf_checks=True)
        token = self.bootstrap(other)
        first = self.post(self.client, self.binding)
        second = self.post(other, token)
        self.assertEqual(second.status_code, 200)
        csrf = self.client.get('/api/auth/csrf').json()['csrfToken']
        self.assertEqual(self.client.post('/api/auth/logout', HTTP_X_CSRFTOKEN=csrf, HTTP_X_JTH_CONTEXT=first[ctx.HEADER]).status_code, 204)
        self.assertEqual(other.get('/api/auth/me', HTTP_X_JTH_CONTEXT=second[ctx.HEADER]).json()['username'], 'A')
        self.assertNotEqual(self.client.cookies[ctx.cookie_name()], other.cookies[ctx.cookie_name()])

    def test_missing_lineage_never_adopts_an_authenticated_cookie(self):
        first = self.post(self.client, self.binding)
        self.assertEqual(first.status_code, 200)
        del self.client.cookies[ctx.cookie_name()]
        new = self.bootstrap(self.client)
        self.assertEqual(self.client.get('/api/auth/me', HTTP_X_JTH_CONTEXT=new).status_code, 401)

    def test_expired_authority_never_recreated_using_client_identifier(self):
        old = self.row()
        GatewaySessionLineage.objects.filter(pk=old.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.client.get('/api/gateway/context', HTTP_X_JTH_CONTEXT=self.binding).status_code, 409)
        self.bootstrap(self.client)
        self.assertNotEqual(self.row().pk, old.pk)
        self.assertEqual(lineage.prune_expired(), 1)
        self.assertEqual(GatewaySessionLineage.objects.count(), 1)

    def test_recovery_challenge_cannot_authenticate_or_replay_after_generation_change(self):
        recovery = lineage.recovery(self.row())
        csrf = self.client.get('/api/auth/csrf').json()['csrfToken']
        first = self.client.post('/api/gateway/session/restart', HTTP_X_CSRFTOKEN=csrf, HTTP_X_JTH_RECOVERY=recovery)
        self.assertEqual(first.status_code, 204)
        self.assertEqual(self.client.get('/api/auth/me', HTTP_X_JTH_CONTEXT=first[ctx.HEADER]).status_code, 401)
        again = self.client.post('/api/gateway/session/restart', HTTP_X_CSRFTOKEN=csrf, HTTP_X_JTH_RECOVERY=recovery)
        self.assertEqual((again.status_code, again.json()['code']), (409, 'gateway_recovery_changed'))
        self.assertEqual(self.client.get('/api/auth/me', HTTP_X_JTH_CONTEXT=recovery).status_code, 409)

    def test_native_unsafe_routes_require_context_but_ordinary_deployments_do_not(self):
        first = self.post(self.client, self.binding)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.client.post('/app/session-writer/').status_code, 409)
        csrf = self.client.get('/api/auth/csrf').json()['csrfToken']
        self.assertEqual(self.client.post('/app/session-writer/', HTTP_X_CSRFTOKEN=csrf, HTTP_X_JTH_CONTEXT=first[ctx.HEADER]).status_code, 200)
        with override_settings(JTH_GATEWAY=False):
            self.assertEqual(self.client.post('/app/session-writer/', HTTP_X_CSRFTOKEN=csrf).status_code, 200)

    def test_postgresql_concurrent_anonymous_signins_first_commit_wins(self):
        if connection.vendor != 'postgresql':
            self.skipTest('Requires isolated PostgreSQL row-lock verification.')
        from accounts.views import LoginView
        entered, competing, release = threading.Event(), threading.Event(), threading.Event()
        original, original_lock = LoginView.post, lineage.lock
        cookie = deepcopy(self.client.cookies)
        def held(view, request):
            if request.data.get('username') == 'B':
                entered.set()
                if not release.wait(10):
                    raise RuntimeError('Barrier not released')
            return original(view, request)
        def observed_lock(pk):
            if threading.current_thread().name.endswith('_1'):
                competing.set()
            return original_lock(pk)
        def sign_in(name):
            close_old_connections()
            try:
                client = Client(enforce_csrf_checks=True)
                client.cookies = deepcopy(cookie)
                return self.post(client, self.binding, name)
            finally:
                close_old_connections()
        with mock.patch.object(LoginView, 'post', held), mock.patch.object(lineage, 'lock', observed_lock), ThreadPoolExecutor(max_workers=2) as executor:
            winner = executor.submit(sign_in, 'B')
            self.assertTrue(entered.wait(10))
            loser = executor.submit(sign_in, 'A')
            try:
                self.assertTrue(competing.wait(10))
            finally:
                release.set()
            first, second = winner.result(15), loser.result(15)
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual((second.status_code, second.json()['code']), (409, 'gateway_session_obsolete'))
        current = Session.objects.get(session_key=self.row().session_key).get_decoded()
        self.assertEqual(current['_auth_user_id'], str(get_user_model().objects.get(username='B').pk))
        self.assertEqual(self.row().generation, 1)

    @override_settings(ROOT_URLCONF='gateway.tests_forms')
    def test_postgresql_native_admin_competing_logins_first_commit_wins(self):
        if connection.vendor != 'postgresql':
            self.skipTest('Requires isolated PostgreSQL row-lock verification.')
        from django.contrib.auth.views import LoginView
        from gateway.tests_forms import Forms, TEMPLATES
        get_user_model().objects.update(is_staff=True)
        with override_settings(TEMPLATES=TEMPLATES):
            page = self.client.get('/admin/login/')
            data = next(f['fields'] for f in Forms(page.content.decode()).forms if f['attrs'].get('id') == 'login-form')
        cookie = deepcopy(self.client.cookies)
        entered, competing, release = threading.Event(), threading.Event(), threading.Event()
        original, original_lock = LoginView.form_valid, lineage.lock
        def held(view, form):
            if form.get_user().username == 'B':
                entered.set()
                if not release.wait(10): raise RuntimeError('Login barrier not released')
            return original(view, form)
        def lock(pk):
            if threading.current_thread().name.endswith('_1'): competing.set()
            return original_lock(pk)
        def sign_in(username):
            close_old_connections()
            try:
                client = Client(enforce_csrf_checks=True);client.cookies=deepcopy(cookie)
                return client.post('/admin/login/', {**data,'username':username,'password':'synthetic-only'})
            finally:
                close_old_connections()
        with mock.patch.object(LoginView, 'form_valid', held), mock.patch.object(lineage, 'lock', lock), ThreadPoolExecutor(max_workers=2) as executor:
            winner = executor.submit(sign_in, 'B')
            self.assertTrue(entered.wait(10))
            loser = executor.submit(sign_in, 'A')
            try: self.assertTrue(competing.wait(10))
            finally: release.set()
            first, second = winner.result(15), loser.result(15)
        self.assertEqual(first.status_code, 302, first.content)
        self.assertContains(second, 'gateway_session_obsolete', status_code=409)
        self.assertNotIn(settings.SESSION_COOKIE_NAME, second.cookies)
        current = Session.objects.get(session_key=self.row().session_key).get_decoded()
        self.assertEqual(current['_auth_user_id'], str(get_user_model().objects.get(username='B').pk))
        self.assertEqual(self.row().generation, 1)
