"""Native form transport, using synthetic accounts and disposable Django databases."""
from copy import deepcopy
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import tempfile
from unittest import mock

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.http import JsonResponse
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import include, path

from accounts.models import Workspace
from applications.models import Application, Override
from gateway import session_context as context, views
from web.urls import urlpatterns as web_patterns


class Forms(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.forms, self.current = [], None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.current = {'attrs':attrs, 'fields':{}, 'bindings':0}
            self.forms.append(self.current)
        elif tag == 'input' and self.current is not None and attrs.get('name'):
            self.current['fields'][attrs['name']] = attrs.get('value','')
            self.current['bindings'] += attrs['name'] == '_jth_context'

    def handle_endtag(self, tag):
        if tag == 'form': self.current = None


@login_required
def multipart(request):
    upload = request.FILES['file']
    data = upload.read()
    request.session['synthetic_upload_seen'] = True
    return JsonResponse({'actor':request.user.pk, 'size':len(data), 'sha256':hashlib.sha256(data).hexdigest()})


urlpatterns = [path('app/', include((web_patterns + [path('multipart/', multipart, name='application-action')], 'web'))),
               path('admin/', admin.site.urls), path('', views.index), path('', include('gateway.urls'))]
TEMPLATES = deepcopy(settings.TEMPLATES)
TEMPLATES[0]['DIRS'] = [settings.BASE_DIR / 'gateway' / 'templates']
PW = 'Synthetic-Password-47!'


class FormHelpers:
    def setUp(self):
        cache.clear()
        self.client = Client(enforce_csrf_checks=True)
        self.a = get_user_model().objects.create_user(username='formA', password=PW, is_staff=True, is_superuser=True)
        self.b = get_user_model().objects.create_user(username='formB', password=PW)
        self.workspace = Workspace.objects.create(owner=self.a, name='Synthetic tracker')
        self.application = Application.objects.create(workspace=self.workspace, section='applications', company='Synthetic Co', role_label='Test role', status='applied')
        self.pipeline = f'/app/w/{self.workspace.pk}/pipeline/'
        self.action = f'/app/w/{self.workspace.pk}/applications/{self.application.pk}/status/'
        root = self.client.get('/')
        self.binding = json.loads(re.search(r'window.JTH_GATEWAY_PAGE = (\{.*?\});', root.content.decode()).group(1))['binding']
        self.login()

    def csrf(self):
        return self.client.get('/api/auth/csrf').json()['csrfToken']

    def api(self, path, body=None):
        response = self.client.post(path, json.dumps(body or {}), content_type='application/json',
                                    HTTP_X_CSRFTOKEN=self.csrf(), HTTP_X_JTH_CONTEXT=self.binding)
        if response.status_code < 300 and context.HEADER in response: self.binding = response[context.HEADER]
        return response

    def login(self, username='formA'):
        result = self.api('/api/auth/login', {'username':username,'password':PW})
        self.assertEqual(result.status_code, 200, result.content)
        return result

    def forms(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.content[:100])
        return Forms(response.content.decode()).forms

    def fields(self, url, action=None, ident=None):
        for form in self.forms(url):
            if form['attrs'].get('method','get').lower() == 'post' and (action is None or form['attrs'].get('action') == action) and (ident is None or form['attrs'].get('id') == ident):
                self.assertEqual(form['bindings'], 1, (url,form['attrs']))
                return form['fields']
        self.fail('Expected a rendered POST form')


@override_settings(JTH_GATEWAY=True, ROOT_URLCONF=__name__, MFA_REQUIRED=False, TEMPLATES=TEMPLATES)
class FormTests(FormHelpers, TestCase):
    def test_pipeline_forms_have_binding_and_submit_without_header(self):
        data = self.fields(self.pipeline, self.action)
        result = self.client.post(self.action, {**data, 'status':'interviewing'})
        self.assertEqual(result.status_code, 302, result.content)
        self.assertEqual(Override.objects.get(application=self.application).manual_status, 'interviewing')

    def test_admin_login_form_has_binding(self):
        self.assertEqual(self.api('/api/auth/logout').status_code, 204)
        data = self.fields('/admin/login/', ident='login-form')
        result = self.client.post('/admin/login/', {**data,'username':self.a.username,'password':PW})
        self.assertEqual(result.status_code, 302, result.content)
        self.assertEqual(self.client.session['_auth_user_id'], str(self.a.pk))

    def test_direct_first_visit_redirects_to_signin_without_loop(self):
        for url in ('/app/','/admin/','/app','/admin'):
            browser = Client()
            first = browser.get(url)
            self.assertEqual(first.status_code, 302, first.content)
            next_page = browser.get(first['Location'])
            self.assertEqual(next_page.status_code, 200)

    def test_all_pipeline_post_and_get_forms_and_kanban(self):
        for url in (self.pipeline, self.pipeline+'?view=kanban', '/app/'):
            response = self.client.get(url, follow=True)
            self.assertEqual(response.status_code, 200)
            for form in Forms(response.content.decode()).forms:
                self.assertEqual(form['bindings'], int(form['attrs'].get('method','get').lower() == 'post'))
                self.assertNotIn('_jth_context', form['attrs'].get('action',''))
        for action in ('follow-up','reset-clock'):
            url = self.action.replace('/status/', '/'+action+'/')
            data = self.fields(self.pipeline, url)
            self.assertEqual(self.client.post(url, data).status_code, 302)
        override = Override.objects.get(application=self.application)
        self.assertEqual(override.next_action, 'Follow up')
        self.assertIsNotNone(override.activity_override)
        data = self.fields(self.pipeline+'?view=kanban', self.action)
        self.assertEqual(self.client.post(self.action, {**data,'status':'ghosted'}).status_code, 302)
        self.assertEqual(self.client.post(self.action, {**data,'status':''}).status_code, 302)
        self.assertIsNone(Override.objects.get(application=self.application).manual_status)

    def test_start_fresh_remains_unimplemented_and_empty_state_has_bound_logout(self):
        response = self.client.get(self.pipeline)
        self.assertContains(response, 'Coming soon">+ Start Fresh')
        get_user_model().objects.create_user(username='empty-native', password=PW)
        self.login('empty-native')
        response = self.client.get('/app/')
        self.assertContains(response, 'No tracker yet')
        self.assertTrue(all(f['bindings'] == 1 for f in Forms(response.content.decode()).forms))

    def test_invalid_pipeline_value_keeps_native_404_and_no_write(self):
        data = self.fields(self.pipeline, self.action)
        response = self.client.post(self.action, {**data,'status':'invalid'})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Override.objects.filter(application=self.application).exists())

    def test_valid_context_does_not_replace_csrf_or_origin_checks(self):
        data = self.fields(self.pipeline, self.action)
        for change, headers in [({'csrfmiddlewaretoken':'invalid'}, {}), ({}, {'HTTP_ORIGIN':'https://foreign.example'})]:
            result = self.client.post(self.action, {**data,**change,'status':'ghosted'}, **headers)
            self.assertEqual(result.status_code, 403)
        self.assertFalse(Override.objects.filter(application=self.application).exists())

    def test_missing_forged_and_wrong_purpose_contexts_fail_without_echo(self):
        from gateway.session_lineage import recovery
        from gateway.models import GatewaySessionLineage
        data = self.fields(self.pipeline, self.action)
        for token in ('', data['_jth_context']+'forged', recovery(GatewaySessionLineage.objects.first())):
            result = self.client.post(self.action, {**data,'_jth_context':token,'status':'ghosted'})
            self.assertEqual(result.status_code, 409)
            self.assertContains(result, 'role="alert"', status_code=409)
            if token: self.assertNotContains(result, token, status_code=409)
            self.assertNotIn(settings.SESSION_COOKIE_NAME, result.cookies)
        self.assertFalse(Override.objects.filter(application=self.application).exists())

    def test_expired_wrong_principal_phase_generation_protocol_and_lineage_fail(self):
        from django.core import signing
        data = self.fields(self.pipeline, self.action)
        snapshot = signing.loads(data['_jth_context'], salt=context.SALT)
        tokens = []
        with mock.patch('django.core.signing.time.time', return_value=0):
            tokens.append(signing.dumps(snapshot, salt=context.SALT))
        for key,value in [('a',str(self.b.pk)),('p','anonymous'),('g','999'),('v',1),('l','00000000-0000-0000-0000-000000000000')]:
            tokens.append(signing.dumps({**snapshot,key:value}, salt=context.SALT))
        for token in tokens:
            self.assertEqual(self.client.post(self.action, {**data,'_jth_context':token,'status':'ghosted'}).status_code, 409)
        self.assertFalse(Override.objects.filter(application=self.application).exists())

    def test_duplicate_and_conflicting_contexts_are_rejected_but_matching_header_works(self):
        from urllib.parse import urlencode
        data = self.fields(self.pipeline, self.action)
        for duplicate in (data['_jth_context'], 'forged'):
            body = urlencode(list(data.items())+[('_jth_context',duplicate),('status','ghosted')])
            self.assertEqual(self.client.post(self.action, body, content_type='application/x-www-form-urlencoded').status_code, 409)
        self.assertEqual(self.client.post(self.action, {**data,'status':'ghosted'}, HTTP_X_JTH_CONTEXT='different').status_code, 409)
        self.assertEqual(self.client.post(self.action, {**data,'status':'ghosted'}, HTTP_X_JTH_CONTEXT=data['_jth_context']).status_code, 302)

    def test_api_remains_header_only_and_does_not_parse_proxy_uploads(self):
        data = self.fields(self.pipeline, self.action)
        self.assertEqual(self.client.post('/api/auth/logout', data).status_code, 409)
        from django.core.handlers.wsgi import WSGIRequest
        with mock.patch.object(WSGIRequest, '_load_post_and_files', side_effect=AssertionError('API body parsed')):
            result = self.client.post('/api/applications/new', {'_jth_context':data['_jth_context'],'file':SimpleUploadedFile('test.bin',b'bytes')})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(self.api('/api/auth/logout').status_code, 204)

    def test_body_transport_not_accepted_on_arbitrary_native_or_get_routes(self):
        data = self.fields(self.pipeline, self.action)
        self.assertEqual(self.client.post(self.pipeline, data).status_code, 409)
        self.assertEqual(self.client.post('/app/unknown/', data).status_code, 409)
        for url in ('/app/','/admin/','/api/auth/csrf'):
            result = self.client.get(url, {'_jth_context':data['_jth_context']})
            self.assertEqual(result.status_code, 409)
            self.assertNotIn(data['_jth_context'], result.get('Location',''))

    def test_context_never_grants_another_workspace_or_application(self):
        foreign = Workspace.objects.create(owner=self.b, name='Private')
        app = Application.objects.create(workspace=foreign, section='applications', company='Private', role_label='Test', status='applied')
        data = self.fields(self.pipeline, self.action)
        for workspace in (foreign, self.workspace):
            result = self.client.post(f'/app/w/{workspace.pk}/applications/{app.pk}/status/', {**data,'status':'ghosted'})
            self.assertEqual(result.status_code, 404)
        self.assertFalse(Override.objects.filter(application=app).exists())

    def test_stale_form_after_switch_same_account_and_A_B_A_never_executes(self):
        for transitions in [('formB',), ('formA',), ('formB','formA')]:
            self.login('formA')
            data = self.fields(self.pipeline, self.action)
            for username in transitions: self.login(username)
            data['csrfmiddlewaretoken'] = self.csrf()  # prove context enforcement, not incidental CSRF rotation
            result = self.client.post(self.action, {**data,'status':'ghosted'})
            self.assertEqual(result.status_code, 409)
            self.assertContains(result, 'gateway_context_changed', status_code=409)
            me = self.client.get('/api/auth/me', HTTP_X_JTH_CONTEXT=self.binding)
            self.assertEqual(me.json()['username'], transitions[-1])
        self.assertFalse(Override.objects.filter(application=self.application).exists())

    def test_native_logout_rotates_generation_and_cannot_log_out_new_identity(self):
        data = self.fields(self.pipeline, '/app/sign-out/')
        old = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        result = self.client.post('/app/sign-out/', data)
        self.assertEqual(result.status_code, 302)
        self.assertEqual(result['Location'], '/')
        self.binding = result[context.HEADER]
        self.assertNotEqual(self.client.cookies[settings.SESSION_COOKIE_NAME].value, old)
        self.login('formB')
        result = self.client.post('/app/sign-out/', {**data,'csrfmiddlewaretoken':self.csrf()})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(self.client.get('/api/auth/me', HTTP_X_JTH_CONTEXT=self.binding).json()['username'], 'formB')

    def test_old_cookie_on_html_entries_reaches_explicit_recovery(self):
        old = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        self.login('formB')
        self.client.cookies[settings.SESSION_COOKIE_NAME] = old
        for url in ('/app/','/admin/','/admin/login/'):
            result = self.client.get(url)
            self.assertContains(result, 'window.JTH_GATEWAY_RECOVERY', status_code=409)
            self.assertNotIn(settings.SESSION_COOKIE_NAME, result.cookies)
            self.assertNotIn('Location', result)

    def test_admin_validation_errors_changes_and_rebound_forms(self):
        url = f'/admin/accounts/workspace/{self.workspace.pk}/change/'
        data = self.fields(url, ident='workspace_form')
        result = self.client.post(url, {**data,'owner':self.a.pk,'name':''})
        self.assertContains(result, 'errorlist')
        forms = Forms(result.content.decode()).forms
        self.assertTrue(all(f['bindings'] == 1 for f in forms if f['attrs'].get('method','get').lower() == 'post'))
        data = next(f['fields'] for f in forms if f['attrs'].get('id') == 'workspace_form')
        result = self.client.post(url, {**data,'owner':self.a.pk,'name':'Changed','calendar_timezone':'UTC','_save':'Save'})
        self.assertEqual(result.status_code, 302, result.content[:200])
        self.workspace.refresh_from_db();self.assertEqual(self.workspace.name, 'Changed')

    def test_admin_user_add_bulk_delete_and_password_forms_all_have_one_binding(self):
        urls = ['/admin/','/admin/accounts/user/add/',f'/admin/accounts/user/{self.b.pk}/password/',
                '/admin/accounts/workspace/','/admin/password_change/','/admin/password_change/done/']
        empty = Workspace.objects.create(owner=self.a, name='Disposable empty')
        urls.append(f'/admin/accounts/workspace/{empty.pk}/delete/')
        for url in urls:
            for form in self.forms(url):
                self.assertEqual(form['bindings'], int(form['attrs'].get('method','get').lower() == 'post'), (url, form['attrs']))
        data = self.fields('/admin/accounts/workspace/', ident='changelist-form')
        result = self.client.post('/admin/accounts/workspace/', {**data,'action':'delete_selected','_selected_action':[empty.pk]})
        self.assertEqual(result.status_code, 200)
        self.assertTrue(all(f['bindings'] == 1 for f in Forms(result.content.decode()).forms))
        self.assertTrue(Workspace.objects.filter(pk=empty.pk).exists())  # confirmation only

    def test_admin_wrong_password_errors_remain_retryable(self):
        self.api('/api/auth/logout')
        data = self.fields('/admin/login/', ident='login-form')
        result = self.client.post('/admin/login/', {**data,'username':self.a.username,'password':'wrong'})
        self.assertContains(result, 'errornote')
        form = next(f for f in Forms(result.content.decode()).forms if f['attrs'].get('id') == 'login-form')
        self.assertEqual(form['bindings'], 1)
        result = self.client.post('/admin/login/', {**form['fields'],'username':self.a.username,'password':PW})
        self.assertEqual(result.status_code, 302)

    def test_admin_password_change_pins_rotation_and_logout_form_on_success_works(self):
        from gateway.models import GatewaySessionLineage
        row = GatewaySessionLineage.objects.get()
        generation = row.generation
        data = self.fields('/admin/password_change/')
        new = 'Another-Synthetic-Password-58!'
        result = self.client.post('/admin/password_change/', {**data,'old_password':PW,'new_password1':new,'new_password2':new})
        self.assertEqual(result.status_code, 302, result.content[:200])
        row.refresh_from_db()
        self.assertEqual(row.generation, generation)
        self.assertEqual(row.session_key, self.client.cookies[settings.SESSION_COOKIE_NAME].value)
        self.a.refresh_from_db();self.assertTrue(self.a.check_password(new))
        data = self.fields('/admin/password_change/done/', '/admin/logout/')
        result = self.client.post('/admin/logout/', data)
        self.assertEqual(result.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
        row.refresh_from_db();self.assertEqual(row.generation, generation+1)

    def test_admin_change_other_user_password_and_permissions_still_apply(self):
        url = f'/admin/accounts/user/{self.b.pk}/password/'
        data = self.fields(url, ident='user_form')
        new = 'Third-Synthetic-Password-69!'
        result = self.client.post(url, {**data,'password1':new,'password2':new,'usable_password':'true'})
        self.assertEqual(result.status_code, 302, result.content[:200])
        self.b.refresh_from_db();self.assertTrue(self.b.check_password(new))
        self.a.is_superuser = False;self.a.save(update_fields=['is_superuser'])
        response = self.client.get(f'/admin/accounts/workspace/{self.workspace.pk}/change/')
        self.assertEqual(response.status_code, 403)

    def test_read_only_admin_actions_remain_denied(self):
        self.assertEqual(self.client.get(f'/admin/applications/application/{self.application.pk}/delete/').status_code, 403)
        data = self.fields(self.pipeline, self.action)
        result = self.client.post(f'/admin/applications/application/{self.application.pk}/delete/', {**data,'post':'yes'})
        self.assertEqual(result.status_code, 403)
        self.assertTrue(Application.objects.filter(pk=self.application.pk).exists())

    def test_multipart_upload_integrity_and_upload_limit(self):
        data = self.fields(self.pipeline, self.action)
        payload = bytes(range(256))*30
        result = self.client.post('/app/multipart/', {**data,'file':SimpleUploadedFile('synthetic.bin',payload)})
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.json(), {'actor':self.a.pk,'size':len(payload),'sha256':hashlib.sha256(payload).hexdigest()})
        with override_settings(JTH_MAX_UPLOAD_MB=0):
            result = self.client.post('/app/multipart/', {**data,'file':SimpleUploadedFile('synthetic.bin',b'test')})
        self.assertEqual(result.status_code, 413)

    def test_non_gateway_forms_have_no_context_and_keep_normal_behavior(self):
        templates = deepcopy(TEMPLATES); templates[0]['DIRS'] = []
        with override_settings(JTH_GATEWAY=False, TEMPLATES=templates):
            for url in (self.pipeline,'/admin/','/admin/accounts/user/add/'):
                self.assertTrue(all(f['bindings'] == 0 for f in self.forms(url)))
            data = next(f['fields'] for f in self.forms(self.pipeline) if f['attrs'].get('action') == self.action)
            result = self.client.post(self.action, {**data,'status':'ghosted'})
            self.assertEqual(result.status_code, 302)

    @override_settings(MFA_REQUIRED=True)
    def test_admin_password_login_requires_mfa_and_recovery_completion_preserves_attempt(self):
        from accounts.tests_mfa_login import make_enrolled
        from gateway.models import GatewaySessionLineage
        user, _, codes = make_enrolled('native-admin')
        user.is_staff = user.is_superuser = True;user.save(update_fields=['is_staff','is_superuser'])
        self.api('/api/auth/logout')
        data = self.fields('/admin/login/', ident='login-form')
        result = self.client.post('/admin/login/', {**data,'username':user.username,'password':'pw123456'})
        self.assertEqual(result.status_code, 302)
        row = GatewaySessionLineage.objects.get(); generation = row.generation
        self.assertEqual(self.client.get('/admin/')['Location'], '/')
        root = self.client.get('/')
        self.binding = json.loads(re.search(r'window.JTH_GATEWAY_PAGE = (\{.*?\});', root.content.decode()).group(1))['binding']
        result = self.api('/api/auth/mfa/verify', {'code':codes[0]})
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(self.client.get('/admin/').status_code, 200)
        row.refresh_from_db(); self.assertEqual(row.generation, generation)


    def test_stale_admin_edit_and_logout_cannot_execute_after_reauthentication(self):
        url = f'/admin/accounts/workspace/{self.workspace.pk}/change/'
        data = self.fields(url, ident='workspace_form')
        logout = self.fields(url, '/admin/logout/')
        self.login()
        csrf = self.csrf()
        result = self.client.post(url, {**data,'csrfmiddlewaretoken':csrf,'name':'Must not save','owner':self.a.pk,'calendar_timezone':'UTC'})
        self.assertContains(result, 'gateway_context_changed', status_code=409)
        self.assertEqual(self.client.post('/admin/logout/', {**logout,'csrfmiddlewaretoken':csrf}).status_code, 409)
        self.workspace.refresh_from_db(); self.assertEqual(self.workspace.name, 'Synthetic tracker')
        self.assertEqual(self.client.get('/api/auth/me', HTTP_X_JTH_CONTEXT=self.binding).json()['username'], 'formA')

    def test_expired_pending_mfa_cannot_mint_a_form_or_fall_back_to_logged_in_actor(self):
        import time
        from accounts.mfa_session import PENDING_KEY
        data = self.fields(self.pipeline, self.action)
        session = self.client.session
        session[PENDING_KEY] = {'uid':self.b.pk, 'ts':time.time()-301}; session.save()
        self.assertContains(self.client.get('/admin/login/'), 'window.JTH_GATEWAY_RECOVERY', status_code=409)
        self.assertEqual(self.client.post(self.action, {**data,'status':'ghosted'}).status_code, 409)
        self.assertFalse(Override.objects.filter(application=self.application).exists())

    def test_obsolete_cookie_rejected_without_parsing_and_sensitive_field_marked(self):
        from django.core.handlers.wsgi import WSGIRequest
        data = self.fields(self.pipeline, self.action)
        old = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        self.login('formB')
        self.client.cookies[settings.SESSION_COOKIE_NAME] = old
        with mock.patch.object(WSGIRequest, '_load_post_and_files', side_effect=AssertionError('obsolete body parsed')):
            result = self.client.post(self.action, {**data,'status':'ghosted'})
        self.assertContains(result, 'gateway_session_obsolete', status_code=409)
        self.assertIn('_jth_context', result.wsgi_request.sensitive_post_parameters)


@override_settings(JTH_GATEWAY=True, ROOT_URLCONF=__name__, MFA_REQUIRED=False, TEMPLATES=TEMPLATES)
class FormTransactionTests(FormHelpers, TransactionTestCase):
    def test_upload_parsing_precedes_lock_and_real_session_save_remains_atomic(self):
        from django.core.files.uploadhandler import MemoryFileUploadHandler
        data = self.fields(self.pipeline, self.action)
        chunks, writes = [], []
        original = MemoryFileUploadHandler.receive_data_chunk
        def receive(handler, raw, start):
            chunks.append(connection.in_atomic_block)
            return original(handler, raw, start)
        def inspect(execute, sql, params, many, ctx):
            if sql.lstrip().upper().startswith(('UPDATE','INSERT','DELETE')) and ('django_session' in sql or 'gateway_gatewaysessionlineage' in sql):
                writes.append((ctx['connection'].alias, ctx['connection'].in_atomic_block))
            return execute(sql, params, many, ctx)
        with mock.patch.object(MemoryFileUploadHandler, 'receive_data_chunk', receive), connection.execute_wrapper(inspect):
            result = self.client.post('/app/multipart/', {**data,'file':SimpleUploadedFile('test.bin',b'upload'*4000)})
        self.assertEqual(result.status_code, 200)
        self.assertTrue(chunks);self.assertFalse(any(chunks))
        self.assertTrue(writes);self.assertTrue(all(alias=='default' and atomic for alias,atomic in writes))

    def test_identity_change_during_multipart_parse_rechecked_after_lock(self):
        from django.core.files.uploadhandler import MemoryFileUploadHandler
        data = self.fields(self.pipeline, self.action)
        original = MemoryFileUploadHandler.receive_data_chunk
        transitioned = []
        def receive(handler, raw, start):
            if not transitioned:
                transitioned.append(True)
                self.assertFalse(connection.in_atomic_block)
                self.login('formB')
            return original(handler, raw, start)
        with mock.patch.object(MemoryFileUploadHandler, 'receive_data_chunk', receive):
            result = self.client.post('/app/multipart/', {**data,'file':SimpleUploadedFile('test.bin',b'upload'*1000)})
        self.assertEqual(result.status_code, 409)
        self.assertContains(result, 'gateway_session_obsolete', status_code=409)
        self.assertNotIn(settings.SESSION_COOKIE_NAME, result.cookies)
        me = self.client.get('/api/auth/me', HTTP_X_JTH_CONTEXT=self.binding)
        self.assertEqual((me.status_code,me.json()['username']), (200,'formB'))

    def test_native_business_write_rolls_back_if_lineage_finalization_fails(self):
        from django.db import OperationalError
        from gateway.session_lineage import Binding
        data = self.fields(self.pipeline, self.action)
        with mock.patch.object(Binding, 'finalize', side_effect=OperationalError('synthetic finalization failure')):
            response = self.client.post(self.action, {**data,'status':'ghosted'})
        self.assertEqual(response.status_code, 503)
        self.assertFalse(Override.objects.filter(application=self.application).exists())
        self.assertNotIn(settings.SESSION_COOKIE_NAME, response.cookies)
        self.assertEqual(self.client.get('/api/auth/me', HTTP_X_JTH_CONTEXT=self.binding).json()['username'], 'formA')

    def test_temporary_uploads_are_parsed_without_lock_and_cleaned_on_success_and_rejection(self):
        from django.core.files.uploadhandler import TemporaryFileUploadHandler
        data = self.fields(self.pipeline, self.action)
        original = TemporaryFileUploadHandler.new_file
        paths = []
        def opened(handler, *args, **kwargs):
            self.assertFalse(connection.in_atomic_block)
            result = original(handler, *args, **kwargs)
            path = Path(handler.file.temporary_file_path())
            self.assertTrue(path.exists()); paths.append(path)
            return result
        payload = bytes(range(256))*40
        with tempfile.TemporaryDirectory(prefix='jth-native-upload-') as directory, override_settings(FILE_UPLOAD_MAX_MEMORY_SIZE=0, FILE_UPLOAD_TEMP_DIR=directory), mock.patch.object(TemporaryFileUploadHandler, 'new_file', opened):
            for valid in (True, False):
                fields = {**data,'file':SimpleUploadedFile('synthetic.bin',payload)}
                if not valid: fields['_jth_context'] = 'forged'
                response = self.client.post('/app/multipart/', fields)
                self.assertEqual(response.status_code, 200 if valid else 409)
                if valid: self.assertEqual(response.json()['sha256'], hashlib.sha256(payload).hexdigest())
                response.close()
                self.assertTrue(paths); self.assertFalse(any(path.exists() for path in paths))
