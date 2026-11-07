"""Passwordless email sign-in and sign-up over real cookie sessions. Mail goes to the in-memory outbox."""
import re
from datetime import timedelta
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from . import email_signin
from .models import SignInCode, User, Workspace
from .tests_mfa_login import HttpMixin, make_enrolled

SETTINGS = dict(EMAIL_SIGNIN_ENABLED=True, EMAIL_SIGNUP_OPEN=True, MFA_EMAIL_FROM="no-reply@example.test")
ADDRESS = "newcomer@example.test"


def last_code():
    return re.search(r"code is (\d{6})", mail.outbox[-1].body).group(1)


class Base(HttpMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient(enforce_csrf_checks=True)

    def start(self, address=ADDRESS, client=None):
        return self.post("/api/auth/email/start", {"email": address}, client)

    def verify(self, code, address=ADDRESS, client=None):
        return self.post("/api/auth/email/verify", {"email": address, "code": code}, client)

    def backdate(self, seconds=3700):
        SignInCode.objects.update(created_at=timezone.now() - timedelta(seconds=seconds))

    def sign_in(self, address=ADDRESS):
        self.assertEqual(self.start(address).status_code, 200)
        return self.verify(last_code(), address)


@override_settings(**SETTINGS)
class SignUpAndSignInTests(Base):
    def test_options_follow_settings(self):
        self.assertEqual(self.client.get("/api/auth/options").json(), {"email_signin": True, "signup_open": True})
        with override_settings(EMAIL_SIGNUP_OPEN=False):
            self.assertEqual(self.client.get("/api/auth/options").json(), {"email_signin": True, "signup_open": False})
        with override_settings(EMAIL_SIGNIN_ENABLED=False):
            self.assertEqual(self.client.get("/api/auth/options").json(), {"email_signin": False, "signup_open": False})

    def test_unknown_address_creates_an_account_with_an_empty_default_workspace(self):
        response = self.start()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"sent": True})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [ADDRESS])
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)  # a code alone signs nobody in
        done = self.verify(last_code())
        self.assertEqual(done.status_code, 200, done.content)
        body = done.json()
        self.assertEqual(body["email"], ADDRESS)
        self.assertEqual(body["mfa_method"], "email_signin")
        self.assertTrue(body["new_account"])
        user = User.objects.get(email=ADDRESS)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(list(Workspace.objects.filter(owner=user).values_list("name", flat=True)), ["My job search"])
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)
        self.assertEqual(self.client.get("/api/workspaces/").status_code, 200)

    def test_existing_account_signs_in_without_a_new_account(self):
        User.objects.create_user(username="alice", email="Alice@Example.test", password="x")
        self.assertEqual(self.start("alice@example.test").status_code, 200)
        done = self.verify(last_code(), "ALICE@example.test")
        self.assertEqual(done.status_code, 200)
        self.assertEqual(done.json()["username"], "alice")
        self.assertFalse(done.json()["new_account"])
        self.assertEqual(User.objects.count(), 1)

    def test_code_is_single_use(self):
        self.start()
        code = last_code()
        self.assertEqual(self.verify(code).status_code, 200)
        self.post("/api/auth/logout")
        self.assertEqual(self.verify(code).status_code, 401)

    def test_wrong_code_signs_nobody_in_and_five_misses_burn_the_code(self):
        self.start()
        good = last_code()
        bad = "000000" if good != "000000" else "111111"
        for _ in range(5):
            response = self.verify(bad)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["code"], "email_code_invalid")
        self.assertEqual(self.verify(good).status_code, 401)  # burned: ask for a new one
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.assertFalse(User.objects.filter(email=ADDRESS).exists())

    def test_expired_code_is_refused(self):
        self.start()
        SignInCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.verify(last_code()).status_code, 401)

    def test_code_for_another_address_is_refused(self):
        self.start()
        self.assertEqual(self.verify(last_code(), "someone-else@example.test").status_code, 401)

    def test_a_new_code_replaces_the_old_one(self):
        self.start()
        first = last_code()
        self.backdate(120)
        self.start()
        second = last_code()
        if first != second:
            self.assertEqual(self.verify(first).status_code, 401)
        self.assertEqual(self.verify(second).status_code, 200)

    def test_invalid_address_is_a_400(self):
        response = self.start("not an address")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "email_invalid")
        self.assertEqual(self.start("x" * 160 + "@example.test").status_code, 400)

    def test_send_failure_leaves_no_usable_code(self):
        with mock.patch("accounts.email_signin.EmailMessage.send", side_effect=OSError("smtp down")):
            response = self.start()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], "email_code_send_failed")
        self.assertEqual(SignInCode.objects.count(), 0)


@override_settings(**SETTINGS)
class WhoMayUseItTests(Base):
    @override_settings(EMAIL_SIGNUP_OPEN=False)
    def test_signup_closed_sends_nothing_and_creates_nothing(self):
        response = self.start()
        self.assertEqual(response.status_code, 200)  # same answer as for an address that can sign in
        self.assertEqual(response.json(), {"sent": True})
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(self.verify("123456").status_code, 401)
        self.assertFalse(User.objects.filter(email=ADDRESS).exists())

    @override_settings(EMAIL_SIGNUP_OPEN=False)
    def test_signup_closed_still_lets_existing_accounts_in(self):
        User.objects.create_user(username="alice", email=ADDRESS, password="x")
        self.assertEqual(self.sign_in().status_code, 200)

    def test_cooldown_looks_the_same_for_an_address_that_cannot_sign_in(self):
        User.objects.create_user(username="boss", email="boss@example.test", password="x", is_staff=True)
        for address in (ADDRESS, "boss@example.test"):
            self.assertEqual(self.start(address).status_code, 200)
            again = self.start(address)
            self.assertEqual(again.status_code, 429, address)
            self.assertEqual(again.json()["code"], "email_code_wait")
            self.assertIn("Retry-After", again)
        self.assertEqual(len(mail.outbox), 1)  # only the sign-up address was emailed

    def test_hourly_cap(self):
        for _ in range(5):
            self.assertEqual(self.start().status_code, 200)
            self.backdate(61)
        sixth = self.start()
        self.assertEqual(sixth.status_code, 429)
        self.assertGreater(sixth.json()["retry_after"], 60)

    def test_staff_without_an_authenticator_cannot_use_it(self):
        User.objects.create_user(username="boss", email="boss@example.test", password="x", is_superuser=True)
        self.assertEqual(self.start("boss@example.test").status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(self.verify("123456", "boss@example.test").status_code, 401)

    def test_inactive_account_cannot_use_it(self):
        User.objects.create_user(username="gone", email=ADDRESS, password="x", is_active=False)
        self.start()
        self.assertEqual(len(mail.outbox), 0)

    def test_two_accounts_with_one_address_are_refused_not_guessed(self):
        User.objects.create_user(username="a", email=ADDRESS, password="x")
        User.objects.create_user(username="b", email=ADDRESS, password="x")
        self.start()
        self.assertEqual(len(mail.outbox), 0)

    def test_a_username_equal_to_the_address_blocks_sign_up(self):
        User.objects.create_user(username=ADDRESS, email="other@example.test", password="x")
        self.start()
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(User.objects.count(), 1)

    def test_disabled_server_answers_404(self):
        with override_settings(EMAIL_SIGNIN_ENABLED=False):
            self.assertEqual(self.start().status_code, 404)
            self.assertEqual(self.verify("123456").status_code, 404)

    def test_needs_a_sender_address(self):
        with override_settings(MFA_EMAIL_FROM=""):
            self.assertEqual(self.start().status_code, 404)


@override_settings(**SETTINGS)
class MfaInteractionTests(Base):
    def setUp(self):
        super().setUp()
        self.user, self.secret, self.codes = make_enrolled()
        self.user.email = ADDRESS
        self.user.save()

    def test_enrolled_account_is_still_asked_for_its_authenticator(self):
        done = self.sign_in()
        self.assertEqual(done.status_code, 200)
        self.assertEqual(done.json(), {"mfa_required": True, "passkey_available": False, "email_code_available": False})
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.client.get("/api/workspaces/").status_code, 401)
        finished = self.post("/api/auth/mfa/verify", {"code": self.code_now(self.secret)})
        self.assertEqual(finished.status_code, 200)
        self.assertEqual(finished.json()["username"], "alice")
        self.assertEqual(self.client.get("/api/workspaces/").status_code, 200)

    def test_staff_with_an_authenticator_may_use_it_and_still_needs_the_authenticator(self):
        User.objects.filter(pk=self.user.pk).update(is_staff=True)
        self.assertEqual(self.sign_in().json()["mfa_required"], True)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    @override_settings(MFA_REQUIRED=True, EMAIL_SIGNIN_SATISFIES_MFA=True)
    def test_satisfies_mfa_never_downgrades_an_enrolled_account(self):
        self.assertEqual(self.sign_in().json()["mfa_required"], True)
        self.assertEqual(self.client.get("/api/workspaces/").status_code, 401)


@override_settings(**SETTINGS, MFA_REQUIRED=True)
class MfaRequiredTests(Base):
    @override_settings(EMAIL_SIGNIN_SATISFIES_MFA=True)
    def test_emailed_code_is_enough_when_the_operator_says_so(self):
        done = self.sign_in()
        self.assertEqual(done.status_code, 200)
        self.assertNotIn("mfa_enrollment_required", done.json())
        self.assertEqual(self.client.get("/api/workspaces/").status_code, 200)

    @override_settings(EMAIL_SIGNIN_SATISFIES_MFA=False)
    def test_otherwise_authenticator_enrolment_is_still_required(self):
        done = self.sign_in()
        self.assertEqual(done.status_code, 200)
        self.assertTrue(done.json()["mfa_enrollment_required"])
        blocked = self.client.get("/api/workspaces/")
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.json()["code"], "mfa_enrollment_required")


@override_settings(**SETTINGS, AUTH_THROTTLE_RATES={"email_signin": "3/min"})
class ThrottleTests(Base):
    def test_requests_per_ip_are_limited(self):
        for index in range(3):
            self.assertEqual(self.start(f"user{index}@example.test").status_code, 200)
        self.assertEqual(self.start("user9@example.test").status_code, 429)


class UnitTests(TestCase):
    def test_normalize_address(self):
        self.assertEqual(email_signin.normalize_address("  Bob@Example.TEST "), "bob@example.test")
        for bad in ("", "bob", "bob@", "a b@example.test"):
            with self.assertRaises(email_signin.InvalidAddress):
                email_signin.normalize_address(bad)
