"""Gateway contract over disposable cookie sessions; actual native auth views."""
import json
import re
import time
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core import signing
from django.http import HttpResponse
from django.core.cache import cache
from django.test import TestCase, Client, override_settings
from django.urls import include, path

from accounts import totp
from accounts.models import MfaDevice, PasskeyCredential
from accounts.tests_mfa_login import make_enrolled
from accounts.tests_passkeys import CRED_ID, REGISTRATION, verified_registration
from core.frontend import index as ordinary_index
from gateway import session_context as ctx, views

def session_writing_template(request):
    request.session["synthetic_message"] = "disposable"
    return HttpResponse("Synthetic template session writer")


urlpatterns = [path("", views.index), path("ordinary/", ordinary_index),
               path("app/session-writer/", session_writing_template), path("", include("gateway.urls"))]
PW = "pw123456"


@override_settings(JTH_GATEWAY=True, ROOT_URLCONF=__name__, MFA_REQUIRED=False)
class ContextTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client(enforce_csrf_checks=True)
        self.a = get_user_model().objects.create_user(username="A", password=PW)
        self.b = get_user_model().objects.create_user(username="B", password=PW)
        self.bootstrap()

    def state(self):
        return signing.loads(self.binding, salt=ctx.SALT)

    def bootstrap(self):
        page = json.loads(re.search(r"window.JTH_GATEWAY_PAGE = (\{.*?\});", self.client.get("/").content.decode()).group(1))
        self.binding = page["binding"]
        self.client.defaults["HTTP_X_JTH_CONTEXT"] = self.binding
        return self.state()

    def post(self, path, body=None, *, binding=None):
        csrf = self.client.get("/api/auth/csrf").json()["csrfToken"]
        r = self.client.post(path, json.dumps(body or {}), content_type="application/json",
                             HTTP_X_CSRFTOKEN=csrf, HTTP_X_JTH_CONTEXT=binding or self.binding)
        if 200 <= r.status_code < 300 and ctx.HEADER in r:
            self.binding = r[ctx.HEADER]
            self.client.defaults["HTTP_X_JTH_CONTEXT"] = self.binding
        return r

    def login(self, username="A"):
        r = self.post("/api/auth/login", {"username": username, "password": PW})
        self.assertEqual(r.status_code, 200, r.content)
        return self.state()

    def test_bootstrap_has_no_authentication_authority(self):
        self.assertEqual(self.state()["p"], "anonymous")
        self.assertEqual(self.client.get("/api/gateway/context").status_code, 204)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.client.get("/api/workspaces/").status_code, 403)

    def test_missing_context_never_bypasses_native_or_proxy_routes(self):
        self.login(); self.client.defaults.clear()
        for route in ("auth/me", "account/passkeys/", "workspaces/", "gateway/context", "unknown"):
            self.assertEqual(self.client.get("/api/" + route).status_code, 409, route)
        for route in ("auth/login", "auth/logout", "auth/email/start", "auth/mfa/verify", "account/passkeys/register/options"):
            self.assertEqual(self.client.post("/api/" + route).status_code, 409, route)

    def test_public_allowlist_is_minimal_and_method_specific(self):
        self.client.defaults.clear()
        for route in ("health", "auth/options", "auth/csrf"):
            self.assertEqual(self.client.get("/api/" + route).status_code, 200, route)
        self.assertEqual(self.client.post("/api/auth/csrf").status_code, 409)
        self.assertEqual(self.client.get("/api/auth/new-route").status_code, 409)

    def test_context_does_not_replace_csrf(self):
        self.assertEqual(self.client.post("/api/auth/login", {"username": "A", "password": PW}).status_code, 403)
        self.login()
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 403)
        self.assertEqual(self.client.get("/api/auth/me").json()["id"], self.a.pk)

    def test_logout_rejects_old_A_context_even_with_fresh_B_csrf(self):
        self.login(); old = self.binding; self.login("B")
        self.assertEqual(self.post("/api/auth/logout", binding=old).status_code, 409)
        self.assertEqual(self.client.get("/api/auth/me").json()["id"], self.b.pk)

    def test_all_account_actions_reject_stale_context(self):
        self.login(); old = self.binding; self.login("B")
        for route in ("account/passkeys/register/options", "account/passkeys/register/verify", "account/mfa/email/begin", "account/mfa/email/confirm", "auth/mfa/enroll/begin"):
            self.assertEqual(self.post("/api/" + route, binding=old).status_code, 409, route)

    def test_same_account_logout_relogin_has_new_generation(self):
        first = self.login(); old = self.binding
        self.assertEqual(self.post("/api/auth/logout").status_code, 204)
        self.assertNotEqual(first["g"], self.login()["g"])
        self.assertEqual(self.client.get("/api/gateway/context", HTTP_X_JTH_CONTEXT=old).status_code, 409)

    def test_same_account_login_without_logout_rotates_generation(self):
        first = self.login(); second = self.login()
        self.assertEqual(first["a"], second["a"])
        self.assertNotEqual(first["g"], second["g"])

    def test_A_B_A_rejects_first_A_context(self):
        first = self.login(); old = self.binding; self.login("B"); final = self.login("A")
        self.assertEqual(first["a"], final["a"])
        self.assertNotEqual(first["g"], final["g"])
        self.assertEqual(self.post("/api/auth/logout", binding=old).status_code, 409)

    def test_concurrent_login_with_obsolete_snapshot_is_rejected(self):
        old = self.binding; self.login()
        self.assertEqual(self.post("/api/auth/login", {"username": "B", "password": PW}, binding=old).status_code, 409)
        self.assertEqual(self.client.get("/api/auth/me").json()["id"], self.a.pk)

    def test_deleted_session_cannot_restore_old_generation(self):
        self.login(); old = self.binding; cookie = self.client.cookies["sessionid"].value
        self.post("/api/auth/logout")
        self.assertFalse(Session.objects.filter(session_key=cookie).exists())
        self.client.cookies["sessionid"] = cookie
        self.assertEqual(self.client.get("/api/gateway/context", HTTP_X_JTH_CONTEXT=old).status_code, 409)
        self.assertFalse(Session.objects.filter(session_key=cookie).exists())

    def test_bad_password_keeps_context_and_native_error(self):
        old = self.binding
        r = self.post("/api/auth/login", {"username": "A", "password": "wrong"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r[ctx.HEADER], old)
        self.assertEqual(self.client.get("/api/gateway/context").status_code, 204)

    def test_wrong_phase_actor_generation_or_protocol_rejected(self):
        state = self.login()
        for key, value in (("p", "anonymous"), ("a", self.b.pk), ("g", "x" * 43), ("v", 1)):
            token = signing.dumps({**state, key: value}, salt=ctx.SALT)
            self.assertEqual(self.client.get("/api/auth/me", HTTP_X_JTH_CONTEXT=token).status_code, 409)

    def test_non_gateway_api_clients_remain_unchanged(self):
        with override_settings(JTH_GATEWAY=False):
            self.client.defaults.clear()
            self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
            self.login()
            self.assertEqual(self.client.get("/api/auth/me").status_code, 200)

    def test_ordinary_template_does_not_require_context(self):
        self.client.defaults.clear()
        self.assertEqual(self.client.get("/ordinary/").status_code, 200)

    def test_email_login_rotates_generation(self):
        before = self.state()
        with mock.patch("accounts.email_signin.verify_code", return_value=(self.a, False)):
            r = self.post("/api/auth/email/verify", {"email": "a@example.test", "code": "123456"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.state()["a"], str(self.a.pk))
        self.assertNotEqual(self.state()["g"], before["g"])

    @override_settings(MFA_REQUIRED=True)
    def test_enrollment_recovery_codes_and_session_key_rotation(self):
        state = self.login(); self.assertEqual(state["p"], "enrollment")
        self.assertEqual(self.client.get("/api/workspaces/").status_code, 403)
        begin = self.post("/api/auth/mfa/enroll/begin")
        self.assertEqual(begin.status_code, 200, begin.content)
        secret = begin.json()["secret"]; key = self.client.session.session_key
        r = self.post("/api/auth/mfa/enroll/confirm", {"code": totp.totp_at(secret, time.time())})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(r.json()["recovery_codes"]), 10)
        self.assertEqual((self.state()["g"], self.state()["p"]), (state["g"], "verified"))
        self.assertNotEqual(key, self.client.session.session_key)
        self.assertEqual(self.client.get("/api/workspaces/").status_code, 200)

    @override_settings(MFA_REQUIRED=True)
    def test_TOTP_completion_retains_attempt_generation(self):
        user, secret, _ = make_enrolled(); state = self.login(user.username)
        self.assertEqual((state["p"], state["a"]), ("pending", str(user.pk)))
        self.assertEqual(self.client.get("/api/account/passkeys/").status_code, 403)
        r = self.post("/api/auth/mfa/verify", {"code": totp.totp_at(secret, time.time())})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((self.state()["g"], self.state()["p"]), (state["g"], "verified"))

    @override_settings(MFA_REQUIRED=True)
    def test_recovery_code_login_and_pending_logout(self):
        user, _, codes = make_enrolled(); self.login(user.username)
        r = self.post("/api/auth/mfa/verify", {"code": codes[0]})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["mfa_method"], "recovery")
        self.post("/api/auth/logout"); self.login(user.username)
        self.assertEqual(self.post("/api/auth/logout").status_code, 204)
        self.assertEqual(self.state()["p"], "anonymous")

    @override_settings(MFA_REQUIRED=True, WEBAUTHN_RP_ID="localhost", WEBAUTHN_ORIGIN="https://localhost:8443")
    def test_passkey_signin_and_management(self):
        user, _, _ = make_enrolled(); device = MfaDevice.objects.get(user=user)
        PasskeyCredential.objects.create(device=device, credential_id=CRED_ID, public_key=b"test", sign_count=3)
        state = self.login(user.username)
        self.assertEqual(self.post("/api/auth/mfa/passkey/options").status_code, 200)
        with mock.patch("accounts.passkeys._verify_authentication", return_value=SimpleNamespace(new_sign_count=4)):
            r = self.post("/api/auth/mfa/passkey/verify", {"credential": REGISTRATION})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.state()["g"], state["g"])
        self.assertEqual(self.client.get("/api/account/passkeys/").status_code, 200)
        self.assertEqual(self.post("/api/account/passkeys/register/options").status_code, 200)
        with mock.patch("accounts.passkeys._verify_registration", return_value=verified_registration(b"cred-2")):
            r = self.post("/api/account/passkeys/register/verify", {"credential": REGISTRATION, "name": "Synthetic"})
        self.assertEqual(r.status_code, 201, r.content)

    def test_pending_signin_never_serializes_previous_authenticated_account(self):
        self.login("A")
        user, secret, _ = make_enrolled()
        with override_settings(MFA_REQUIRED=True):
            state = self.login(user.username)
            self.assertEqual((state["p"], state["a"]), ("pending", str(user.pk)))
            self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
            self.assertEqual(self.client.get("/api/workspaces/").status_code, 403)
            self.assertEqual(self.post("/api/auth/mfa/verify", {"code": totp.totp_at(secret, time.time())}).status_code, 200)
            self.assertEqual(self.client.get("/api/auth/me").json()["id"], user.pk)

    def test_deactivated_pending_user_cannot_fall_back_to_previous_account(self):
        self.login("A")
        user, _, _ = make_enrolled()
        with override_settings(MFA_REQUIRED=True):
            self.login(user.username)
            user.is_active = False; user.save(update_fields=["is_active"])
            self.assertEqual(self.post("/api/auth/mfa/verify", {"code": "123456"}).status_code, 401)

    def test_rejected_old_cookie_response_does_not_delete_current_cookie(self):
        self.login(); old = self.binding; cookie = self.client.cookies["sessionid"].value
        self.post("/api/auth/logout")
        self.client.cookies["sessionid"] = cookie
        response = self.client.get("/api/gateway/context", HTTP_X_JTH_CONTEXT=old)
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("sessionid", response.cookies)

    @override_settings(MFA_REQUIRED=True, MFA_EMAIL_CODES_ENABLED=True, MFA_EMAIL_FROM="test@example.test")
    def test_email_second_factor_and_management_remain_functional(self):
        from accounts.tests_email_codes import last_code
        from accounts.models import EmailCode
        from django.utils import timezone
        from datetime import timedelta
        user, _, recovery = make_enrolled()
        user.email = "alice@example.test"; user.save(update_fields=["email"])
        self.login(user.username)
        self.assertEqual(self.post("/api/auth/mfa/verify", {"code": recovery[0]}).status_code, 200)
        self.assertEqual(self.post("/api/account/mfa/email/begin").status_code, 200)
        self.assertEqual(self.post("/api/account/mfa/email/confirm", {"code": last_code()}).status_code, 200)
        self.post("/api/auth/logout")
        EmailCode.objects.update(created_at=timezone.now() - timedelta(hours=2))
        state = self.login(user.username)
        self.assertEqual(self.post("/api/auth/mfa/email/send").status_code, 200)
        r = self.post("/api/auth/mfa/email/verify", {"code": last_code()})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((self.state()["g"], self.state()["p"]), (state["g"], "verified"))

    def test_pending_second_account_serves_login_shell_even_when_mfa_optional(self):
        self.login("A")
        user, _, _ = make_enrolled()
        self.login(user.username)
        response = self.client.get("/")
        self.assertContains(response, "window.JTH_GATEWAY_LOGIN = true;")
        self.assertNotContains(response, "window.JTH_GATEWAY = true;")


    def test_public_health_does_not_load_stale_cookie_and_delete_new_session(self):
        self.login(); old_cookie = self.client.cookies["sessionid"].value
        self.post("/api/auth/logout")
        self.client.cookies["sessionid"] = old_cookie
        self.client.defaults.clear()
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("sessionid", response.cookies)

    def test_template_session_writes_preserve_bound_context_without_header_requirement(self):
        self.login(); old = self.binding
        self.client.defaults.clear()
        response = self.client.get("/app/session-writer/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session["synthetic_message"], "disposable")
        self.assertEqual(self.client.get("/api/gateway/context", HTTP_X_JTH_CONTEXT=old).status_code, 204)

    def test_obsolete_cookie_cannot_silently_bootstrap_competing_login(self):
        self.login('A')
        delayed = Client(enforce_csrf_checks=True)
        delayed.cookies.update(self.client.cookies)
        csrf = delayed.get('/api/auth/csrf').json()['csrfToken']
        held = delayed.post('/api/auth/login', json.dumps({'username':'B','password':PW}),
                            content_type='application/json', HTTP_X_CSRFTOKEN=csrf,
                            HTTP_X_JTH_CONTEXT=self.binding)
        self.assertEqual(held.status_code, 200)
        # B committed first, but its response cookies have not reached the browser.
        root = self.client.get('/')
        self.assertContains(root, 'window.JTH_GATEWAY_RECOVERY', status_code=409)
        denied = self.post('/api/auth/login', {'username':'A','password':PW})
        self.assertEqual(denied.status_code, 409)
        self.assertEqual(denied.json()['code'], 'gateway_session_obsolete')
        self.client.cookies.update(held.cookies)
        me = self.client.get('/api/auth/me', HTTP_X_JTH_CONTEXT=held[ctx.HEADER])
        self.assertEqual(me.json()['username'], 'B')

    @override_settings(MFA_REQUIRED=True)
    def test_expiry_at_native_boundary_never_falls_back_to_previous_actor(self):
        from accounts import mfa, mfa_session
        from accounts.views import MfaVerifyView
        a, _, codes = make_enrolled('boundaryA')
        b, _, _ = make_enrolled('boundaryB')
        self.login(a.username)
        self.assertEqual(self.post('/api/auth/mfa/verify', {'code':codes[0]}).status_code, 200)
        self.login(b.username)
        original = MfaVerifyView.post
        def expire_before_view(view, request):
            pending = request.session[mfa_session.PENDING_KEY]
            request.session[mfa_session.PENDING_KEY] = {**pending, 'ts':int(time.time())-301}
            return original(view, request)
        with mock.patch.object(MfaVerifyView, 'post', expire_before_view):
            response = self.post('/api/auth/mfa/verify', {'code':codes[1]})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['code'], 'mfa_session_expired')
        self.assertEqual(mfa.remaining_recovery_codes(a), 9)


    @override_settings(MFA_REQUIRED=True)
    def test_legitimate_enrollment_denial_preserves_current_context_for_setup(self):
        self.login()
        result = self.client.get('/api/workspaces/')
        self.assertEqual((result.status_code, result.json()['code']), (403, 'mfa_enrollment_required'))
        self.assertEqual(result[ctx.HEADER], self.binding)
        self.assertEqual(self.post('/api/auth/mfa/enroll/begin').status_code, 200)


    @override_settings(MFA_REQUIRED=True, MFA_EMAIL_CODES_ENABLED=True)
    def test_all_secondary_factor_boundaries_reject_expired_pending_identity(self):
        from accounts import mfa_session
        from accounts.views import MfaVerifyView
        from accounts.passkey_views import PasskeySignInOptionsView, PasskeySignInVerifyView
        from accounts.email_code_views import EmailSignInSendView, EmailSignInVerifyView
        user, _, codes = make_enrolled('all-boundaries')
        self.login(user.username)
        cases = [
            (MfaVerifyView, '/api/auth/mfa/verify', {'code':codes[0]}),
            (PasskeySignInOptionsView, '/api/auth/mfa/passkey/options', {}),
            (PasskeySignInVerifyView, '/api/auth/mfa/passkey/verify', {'credential':REGISTRATION}),
            (EmailSignInSendView, '/api/auth/mfa/email/send', {}),
            (EmailSignInVerifyView, '/api/auth/mfa/email/verify', {'code':'123456'}),
        ]
        for view_class, route, body in cases:
            original = view_class.post
            def expired(view, request, original=original):
                pending = request.session[mfa_session.PENDING_KEY]
                request.session[mfa_session.PENDING_KEY] = {**pending, 'ts':time.time()-301}
                return original(view, request)
            with self.subTest(route=route), mock.patch.object(view_class, 'post', expired):
                result = self.post(route, body)
                self.assertEqual((result.status_code, result.json()['code']), (401, 'mfa_session_expired'))
        from accounts import mfa
        self.assertEqual(mfa.remaining_recovery_codes(user), 10)

    def test_native_authentication_api_never_accepts_form_context_instead_of_header(self):
        csrf = self.client.get('/api/auth/csrf').json()['csrfToken']
        self.client.defaults.clear()
        response = self.client.post('/api/auth/login', {'username':'A','password':PW,'csrfmiddlewaretoken':csrf,'_jth_context':self.binding})
        self.assertEqual(response.status_code, 409)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(self.client.get('/api/gateway/context', HTTP_X_JTH_CONTEXT=self.binding).status_code, 204)

    def test_optional_mfa_enrollment_from_verified_session_succeeds(self):
        from accounts import mfa_session
        state = self.login()
        self.assertEqual(state['p'], 'verified')
        key = self.client.session.session_key
        begin = self.post('/api/auth/mfa/enroll/begin')
        self.assertEqual(begin.status_code, 200)
        result = self.post('/api/auth/mfa/enroll/confirm', {'code':totp.totp_at(begin.json()['secret'], time.time())})
        self.assertEqual(result.status_code, 200, result.content)
        self.assertIsNotNone(MfaDevice.objects.get(user=self.a).confirmed_at)
        self.assertEqual(len(result.json()['recovery_codes']), 10)
        self.assertTrue(self.client.session[mfa_session.VERIFIED_KEY])
        self.assertNotEqual(self.client.session.session_key, key)
        self.assertEqual((self.state()['a'],self.state()['g'],self.state()['p']), (str(self.a.pk),state['g'],'verified'))
        self.assertEqual(self.client.get('/api/auth/me').json()['id'], self.a.pk)
        self.assertTrue(self.client.get('/api/auth/mfa/status').json()['enrolled'])

    @override_settings(MFA_REQUIRED=True)
    def test_authorized_reenrollment_after_operator_reset_succeeds(self):
        from accounts import mfa_session
        self.login()
        begin = self.post('/api/auth/mfa/enroll/begin')
        self.assertEqual(self.post('/api/auth/mfa/enroll/confirm', {'code':totp.totp_at(begin.json()['secret'], time.time())}).status_code, 200)
        # Reset only this disposable account's device, as the permitted admin operation does.
        MfaDevice.objects.filter(user=self.a).delete()
        state = self.bootstrap()
        self.assertEqual(state['p'], 'verified')
        key = self.client.session.session_key
        begin = self.post('/api/auth/mfa/enroll/begin')
        self.assertEqual(begin.status_code, 200)
        result = self.post('/api/auth/mfa/enroll/confirm', {'code':totp.totp_at(begin.json()['secret'], time.time())})
        self.assertEqual(result.status_code, 200, result.content)
        self.assertIsNotNone(MfaDevice.objects.get(user=self.a).confirmed_at)
        self.assertEqual(len(result.json()['recovery_codes']), 10)
        self.assertTrue(self.client.session[mfa_session.VERIFIED_KEY])
        self.assertNotEqual(self.client.session.session_key, key)
        self.assertEqual((self.state()['a'],self.state()['g'],self.state()['p']), (str(self.a.pk),state['g'],'verified'))
        self.assertEqual(self.client.get('/api/auth/me').json()['id'], self.a.pk)
        self.assertEqual(self.client.get('/api/workspaces/').status_code, 200)

    def test_verified_enrollment_rejects_stale_generations_and_cross_account_attempts(self):
        self.login()
        begin = self.post('/api/auth/mfa/enroll/begin')
        code = totp.totp_at(begin.json()['secret'], time.time())
        for transitions in [('A',), ('B',), ('B','A')]:
            self.login('A')
            previous = self.binding
            for username in transitions:
                self.login(username)
            for path, body in [('/api/auth/mfa/enroll/begin', {}), ('/api/auth/mfa/enroll/confirm', {'code':code})]:
                result = self.post(path, body, binding=previous)
                self.assertEqual(result.status_code, 409)
            self.assertEqual(self.client.get('/api/auth/me').json()['username'], transitions[-1])
        self.assertIsNone(MfaDevice.objects.get(user=self.a).confirmed_at)
        self.assertFalse(MfaDevice.objects.filter(user=self.b).exists())

    def test_enrollment_rechecks_actual_request_principal_at_completion(self):
        from accounts import mfa_session
        from accounts.views import MfaEnrollConfirmView
        self.login()
        begin = self.post('/api/auth/mfa/enroll/begin')
        original = MfaEnrollConfirmView.post
        def changed(view, request):
            request.user = self.b
            mfa_session.check_completion(request, self.a)  # formerly captured actor cannot authorize B
            return original(view, request)
        with mock.patch.object(MfaEnrollConfirmView, 'post', changed):
            result = self.post('/api/auth/mfa/enroll/confirm', {'code':totp.totp_at(begin.json()['secret'], time.time())})
        self.assertEqual((result.status_code,result.json()['code']), (409,'gateway_principal_changed'))
        self.assertIsNone(MfaDevice.objects.get(user=self.a).confirmed_at)
        self.assertFalse(MfaDevice.objects.filter(user=self.b).exists())
        self.assertEqual(self.client.get('/api/auth/me').json()['id'], self.a.pk)

    def test_enrollment_rechecks_phase_and_cannot_use_a_new_pending_identity(self):
        from accounts import mfa_session
        from accounts.views import MfaEnrollConfirmView
        self.login()
        begin = self.post('/api/auth/mfa/enroll/begin')
        original = MfaEnrollConfirmView.post
        def changed(view, request):
            request.session[mfa_session.PENDING_KEY] = {'uid':self.b.pk,'ts':int(time.time())}
            return original(view, request)
        with mock.patch.object(MfaEnrollConfirmView, 'post', changed):
            result = self.post('/api/auth/mfa/enroll/confirm', {'code':totp.totp_at(begin.json()['secret'], time.time())})
        self.assertEqual((result.status_code,result.json()['code']), (409,'gateway_principal_changed'))
        self.assertIsNone(MfaDevice.objects.get(user=self.a).confirmed_at)
        self.assertEqual(self.client.get('/api/auth/me').json()['id'], self.a.pk)

    def test_enrollment_context_still_requires_csrf_and_pending_signin_cannot_enroll(self):
        self.login()
        begin = self.post('/api/auth/mfa/enroll/begin')
        code = totp.totp_at(begin.json()['secret'], time.time())
        result = self.client.post('/api/auth/mfa/enroll/confirm', {'code':code}, HTTP_X_JTH_CONTEXT=self.binding)
        self.assertEqual(result.status_code, 403)
        self.assertIsNone(MfaDevice.objects.get(user=self.a).confirmed_at)
        user, _, _ = make_enrolled('pending-enroll')
        self.login(user.username)
        for path in ('/api/auth/mfa/enroll/begin','/api/auth/mfa/enroll/confirm'):
            self.assertEqual(self.post(path, {'code':code}).status_code, 403)
        self.assertEqual(self.state()['p'], 'pending')
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)

    def test_ordinary_django_optional_enrollment_still_succeeds(self):
        from accounts import mfa_session
        with override_settings(JTH_GATEWAY=False):
            self.client.defaults.clear()
            self.assertEqual(self.post('/api/auth/login', {'username':'A','password':PW}).status_code, 200)
            begin = self.post('/api/auth/mfa/enroll/begin')
            result = self.post('/api/auth/mfa/enroll/confirm', {'code':totp.totp_at(begin.json()['secret'], time.time())})
            self.assertEqual(result.status_code, 200)
            self.assertIsNotNone(MfaDevice.objects.get(user=self.a).confirmed_at)
            self.assertTrue(self.client.session[mfa_session.VERIFIED_KEY])
            self.assertEqual(self.client.get('/api/auth/me').json()['id'], self.a.pk)
