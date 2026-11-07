"""Two-step login, enforcement, admin bypass and throttling over real cookie sessions."""
import time

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from . import mfa, totp
from .models import MfaDevice, User

PW = "pw123456"


def make_enrolled(username="alice"):
    """Enrolled user. Enrolment uses a past time step so a code for 'now' is not a replay."""
    user = User.objects.create_user(username=username, password=PW)
    secret, _uri = mfa.begin_enrollment(user)
    past = time.time() - 90
    codes = mfa.confirm_enrollment(user, totp.totp_at(secret, past), now=past)
    return user, secret, codes


class HttpMixin:
    def post(self, path, data=None, client=None):
        client = client or self.client
        token = client.get("/api/auth/csrf").data["csrfToken"]
        return client.post(path, data or {}, format="json", HTTP_X_CSRFTOKEN=token)

    def login(self, username="alice", client=None):
        return self.post("/api/auth/login", {"username": username, "password": PW}, client)

    def code_now(self, secret):
        return totp.totp_at(secret, time.time())


class TwoStepLoginTests(HttpMixin, TestCase):
    def setUp(self):
        self.user, self.secret, self.codes = make_enrolled()
        self.client = APIClient(enforce_csrf_checks=True)

    def test_password_alone_creates_no_session(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"mfa_required": True})
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.client.get("/api/workspaces/").status_code, 401)

    def test_correct_code_completes_login(self):
        self.login()
        response = self.post("/api/auth/mfa/verify", {"code": self.code_now(self.secret)})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["username"], "alice")
        self.assertEqual(body["mfa_method"], "totp")
        self.assertEqual(body["recovery_codes_remaining"], 10)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)
        self.assertEqual(self.client.get("/api/workspaces/").status_code, 200)

    def test_wrong_code_keeps_signed_out(self):
        self.login()
        response = self.post("/api/auth/mfa/verify", {"code": "000000"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "mfa_invalid_code")
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_recovery_code_logs_in_once(self):
        self.login()
        response = self.post("/api/auth/mfa/verify", {"code": self.codes[0]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mfa_method"], "recovery")
        self.assertEqual(response.json()["recovery_codes_remaining"], 9)
        self.assertEqual(self.post("/api/auth/logout").status_code, 204)
        self.login()
        self.assertEqual(self.post("/api/auth/mfa/verify", {"code": self.codes[0]}).status_code, 401)

    def test_verify_without_a_pending_login_is_refused(self):
        response = self.post("/api/auth/mfa/verify", {"code": self.code_now(self.secret)})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "mfa_session_expired")

    def test_pending_login_expires(self):
        self.login()
        session = self.client.session
        pending = session["mfa_pending"]
        pending["ts"] -= 1000
        session["mfa_pending"] = pending
        session.save()
        response = self.post("/api/auth/mfa/verify", {"code": self.code_now(self.secret)})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "mfa_session_expired")

    @override_settings(MFA_LOCKOUT_THRESHOLD=2)
    def test_lockout_applies_over_http_even_to_a_correct_code(self):
        self.login()
        for _ in range(2):
            self.assertEqual(self.post("/api/auth/mfa/verify", {"code": "000000"}).status_code, 401)
        response = self.post("/api/auth/mfa/verify", {"code": self.code_now(self.secret)})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "mfa_locked")
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_each_login_needs_a_fresh_verification(self):
        self.login()
        self.post("/api/auth/mfa/verify", {"code": self.codes[1]})
        self.post("/api/auth/logout")
        self.assertEqual(self.login().json(), {"mfa_required": True})
        self.assertEqual(self.client.get("/api/workspaces/").status_code, 401)

    def test_bad_input_is_validated(self):
        self.login()
        for body in ({}, {"code": ""}, {"code": "x" * 33}):
            self.assertEqual(self.post("/api/auth/mfa/verify", body).status_code, 400)


@override_settings(MFA_REQUIRED=True)
class EnforcementTests(HttpMixin, TestCase):
    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=True)

    def test_unenrolled_user_is_restricted_until_enrolment_completes(self):
        User.objects.create_user(username="newbie", password=PW)
        response = self.login("newbie")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["mfa_enrollment_required"])
        blocked = self.client.get("/api/workspaces/")
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.json()["code"], "mfa_enrollment_required")
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)
        state = self.client.get("/api/auth/mfa/status").json()
        self.assertEqual((state["enrolled"], state["required"], state["verified"]), (False, True, False))

        begin = self.post("/api/auth/mfa/enroll/begin")
        self.assertEqual(begin.status_code, 200)
        secret = begin.json()["secret"]
        self.assertTrue(begin.json()["otpauth_uri"].startswith("otpauth://totp/"))
        self.assertTrue(begin.json()["qr_svg"].lstrip().startswith("<svg"))
        self.assertNotIn(secret, begin.json()["qr_svg"])  # image carries modules, never the text key
        self.assertEqual(self.post("/api/auth/mfa/enroll/confirm", {"code": "000000"}).status_code, 400)
        self.assertEqual(self.client.get("/api/workspaces/").status_code, 403)

        done = self.post("/api/auth/mfa/enroll/confirm", {"code": self.code_now(secret)})
        self.assertEqual(done.status_code, 200)
        self.assertEqual(len(done.json()["recovery_codes"]), 10)
        self.assertEqual(self.client.get("/api/workspaces/").status_code, 200)
        state = self.client.get("/api/auth/mfa/status").json()
        self.assertEqual((state["enrolled"], state["verified"], state["recovery_codes_remaining"]), (True, True, 10))

    def test_enrolled_user_cannot_start_enrolment_again(self):
        _user, secret, _codes = make_enrolled()
        self.login()
        self.post("/api/auth/mfa/verify", {"code": self.code_now(secret)})
        response = self.post("/api/auth/mfa/enroll/begin")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "mfa_already_enrolled")

    def test_password_only_session_cannot_reach_api_or_admin(self):
        # A session created without our login view, as Django's /admin/ login would.
        user, secret, _codes = make_enrolled("op")
        user.is_staff = user.is_superuser = True
        user.save()
        self.client.force_login(user)
        blocked = self.client.get("/api/workspaces/")
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.json()["code"], "mfa_required")
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/")
        # Verification completes it, after which both open.
        self.assertEqual(self.post("/api/auth/mfa/verify", {"code": self.code_now(secret)}).status_code, 200)
        self.assertEqual(self.client.get("/api/workspaces/").status_code, 200)
        self.assertEqual(self.client.get("/admin/").status_code, 200)

    def test_public_surfaces_stay_open_to_unverified_sessions(self):
        user, _secret, _codes = make_enrolled("op")
        self.client.force_login(user)
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/api/auth/mfa/status").status_code, 200)

    def test_no_enforcement_when_not_required(self):
        with override_settings(MFA_REQUIRED=False):
            user = User.objects.create_user(username="dev", password=PW)
            self.client.force_login(user)
            self.assertEqual(self.client.get("/api/workspaces/").status_code, 200)


class AdminResetTests(TestCase):
    def test_admin_shows_no_secrets_and_deleting_resets(self):
        user, secret, codes = make_enrolled("target")
        operator = User.objects.create_superuser(username="op", password=PW)
        self.client.force_login(operator)
        device = MfaDevice.objects.get(user=user)
        page = self.client.get(f"/admin/accounts/mfadevice/{device.pk}/change/")
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        for secret_text in (secret, device.secret_encrypted, codes[0]):
            self.assertNotIn(secret_text, body)
        response = self.client.post(f"/admin/accounts/mfadevice/{device.pk}/delete/", {"post": "yes"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(mfa.is_enrolled(user))
        self.assertEqual(self.client.get("/admin/accounts/mfadevice/add/").status_code, 403)


class ThrottleTests(HttpMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient(enforce_csrf_checks=True)

    @override_settings(AUTH_THROTTLE_RATES={"auth_login": "3/min"})
    def test_login_attempts_are_rate_limited(self):
        User.objects.create_user(username="alice", password=PW)
        codes = [self.post("/api/auth/login", {"username": "alice", "password": "wrong"}).status_code for _ in range(4)]
        self.assertEqual(codes, [401, 401, 401, 429])

    @override_settings(AUTH_THROTTLE_RATES={"mfa": "3/min"})
    def test_code_attempts_are_rate_limited(self):
        codes = [self.post("/api/auth/mfa/verify", {"code": "000000"}).status_code for _ in range(4)]
        self.assertEqual(codes, [401, 401, 401, 429])

    def test_unthrottled_when_no_rate_configured(self):
        User.objects.create_user(username="alice", password=PW)
        for _ in range(12):
            self.assertEqual(self.post("/api/auth/login", {"username": "alice", "password": "wrong"}).status_code, 401)
