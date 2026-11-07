"""Emailed sign-in codes over real cookie sessions. Mail goes to Django's in-memory outbox."""
import re
import time
from datetime import timedelta
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from . import email_codes, mfa, totp
from .models import EmailCode, MfaDevice, User
from .tests_mfa_login import HttpMixin, make_enrolled

EMAIL_SETTINGS = dict(MFA_EMAIL_CODES_ENABLED=True, MFA_EMAIL_FROM="no-reply@example.test")
ADDRESS = "alice@example.test"


def last_code():
    return re.search(r"code is (\d{6})", mail.outbox[-1].body).group(1)


class EmailMixin(HttpMixin):
    def delete(self, path, client=None):
        client = client or self.client
        token = client.get("/api/auth/csrf").data["csrfToken"]
        return client.delete(path, HTTP_X_CSRFTOKEN=token)

    def backdate_sends(self, seconds=3700):
        """Age codes sent within the last hour (older ones stay old, so the hourly cap is honest)."""
        recent = EmailCode.objects.filter(created_at__gt=timezone.now() - timedelta(hours=1))
        recent.update(created_at=timezone.now() - timedelta(seconds=seconds))

    def sign_in_with_code(self, secret, client=None):
        """First call uses the authenticator code; a code cannot be replayed within its 30-second
        step, so every later sign-in in the same test spends a recovery code instead."""
        client = client or self.client
        used = getattr(self, "_sign_ins", 0)
        self._sign_ins = used + 1
        code = self.code_now(secret) if used == 0 else self.codes[used]
        self.login("alice", client)
        self.assertEqual(self.post("/api/auth/mfa/verify", {"code": code}, client).status_code, 200)

    def enable_email_codes(self):
        """Opt in through the API from a verified session, then sign out."""
        self.sign_in_with_code(self.secret)
        self.assertEqual(self.post("/api/account/mfa/email/begin").status_code, 200)
        done = self.post("/api/account/mfa/email/confirm", {"code": last_code()})
        self.assertEqual(done.status_code, 200, done.content)
        self.post("/api/auth/logout")
        mail.outbox.clear()
        self.backdate_sends()


@override_settings(**EMAIL_SETTINGS)
class EnableTests(EmailMixin, TestCase):
    def setUp(self):
        self.user, self.secret, self.codes = make_enrolled()
        self.user.email = ADDRESS
        self.user.save()
        self.client = APIClient(enforce_csrf_checks=True)

    def test_opt_in_flow(self):
        self.sign_in_with_code(self.secret)
        state = self.client.get("/api/account/mfa/email/").json()
        self.assertEqual(state, {"available": True, "enabled": False, "address": None, "pending_address": None, "has_email_on_file": True})
        begin = self.post("/api/account/mfa/email/begin")
        self.assertEqual(begin.status_code, 200)
        self.assertEqual(begin.json(), {"sent_to": "a***@example.test"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [ADDRESS])
        self.assertEqual(mail.outbox[0].from_email, "no-reply@example.test")
        code = last_code()
        self.assertNotIn(code, mail.outbox[0].subject)
        self.assertFalse(EmailCode.objects.filter(code_hash__contains=code).exists())  # never stored in clear
        bad = self.post("/api/account/mfa/email/confirm", {"code": "000000" if code != "000000" else "111111"})
        self.assertEqual((bad.status_code, bad.json()["code"]), (400, "email_code_invalid"))
        self.assertEqual(MfaDevice.objects.get().email_codes_address, "")
        done = self.post("/api/account/mfa/email/confirm", {"code": code})
        self.assertEqual((done.status_code, done.json()), (200, {"enabled": True, "address": "a***@example.test"}))
        self.assertEqual(MfaDevice.objects.get().email_codes_address, ADDRESS)
        self.assertTrue(self.client.get("/api/account/mfa/email/").json()["enabled"])

    def test_pending_confirmation_survives_a_reload(self):
        self.sign_in_with_code(self.secret)
        self.assertIsNone(self.client.get("/api/account/mfa/email/").json()["pending_address"])
        self.post("/api/account/mfa/email/begin")
        self.assertEqual(self.client.get("/api/account/mfa/email/").json()["pending_address"], "a***@example.test")
        EmailCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertIsNone(self.client.get("/api/account/mfa/email/").json()["pending_address"])

    def test_needs_a_signed_in_session(self):
        self.assertEqual(self.client.get("/api/account/mfa/email/").status_code, 401)
        self.assertEqual(self.post("/api/account/mfa/email/begin").status_code, 401)

    @override_settings(MFA_REQUIRED=True)
    def test_unverified_session_cannot_enable(self):
        self.client.force_login(self.user)  # password-only session
        blocked = self.post("/api/account/mfa/email/begin")
        self.assertEqual((blocked.status_code, blocked.json()["code"]), (403, "mfa_required"))
        self.assertEqual(mail.outbox, [])

    def test_requires_the_authenticator_app_first(self):
        User.objects.create_user(username="newbie", password="pw123456", email="n@example.test")
        self.client.post("/api/auth/login", {"username": "newbie", "password": "pw123456"}, format="json",
                         HTTP_X_CSRFTOKEN=self.client.get("/api/auth/csrf").data["csrfToken"])
        response = self.post("/api/account/mfa/email/begin")
        self.assertEqual((response.status_code, response.json()["code"]), (400, "mfa_not_enrolled"))

    def test_account_without_an_email_address(self):
        self.user.email = ""
        self.user.save()
        self.sign_in_with_code(self.secret)
        response = self.post("/api/account/mfa/email/begin")
        self.assertEqual((response.status_code, response.json()["code"]), (400, "email_address_missing"))
        self.assertEqual(mail.outbox, [])

    def test_failed_send_leaves_no_usable_code(self):
        self.sign_in_with_code(self.secret)
        with mock.patch("accounts.email_codes.EmailMessage.send", side_effect=OSError("smtp down")):
            response = self.post("/api/account/mfa/email/begin")
        self.assertEqual((response.status_code, response.json()["code"]), (502, "email_code_send_failed"))
        self.assertFalse(EmailCode.objects.exists())

    def test_disable(self):
        self.enable_email_codes()
        self.sign_in_with_code(self.secret)
        self.assertEqual(self.delete("/api/account/mfa/email/").status_code, 204)
        self.assertFalse(self.client.get("/api/account/mfa/email/").json()["enabled"])
        self.assertFalse(EmailCode.objects.exists())
        self.post("/api/auth/logout")
        self.assertFalse(self.login().json()["email_code_available"])

    def test_operator_reset_removes_it(self):
        self.enable_email_codes()
        self.sign_in_with_code(self.secret)
        mfa.reset(self.user)
        self.assertFalse(MfaDevice.objects.exists())
        self.assertFalse(EmailCode.objects.exists())

    @override_settings(MFA_EMAIL_CODES_ENABLED=False)
    def test_unavailable_when_switched_off(self):
        self.sign_in_with_code(self.secret)
        self.assertFalse(self.client.get("/api/account/mfa/email/").json()["available"])
        response = self.post("/api/account/mfa/email/begin")
        self.assertEqual((response.status_code, response.json()["code"]), (404, "email_codes_unavailable"))


@override_settings(**EMAIL_SETTINGS)
class SignInTests(EmailMixin, TestCase):
    def setUp(self):
        self.user, self.secret, self.codes = make_enrolled()
        self.user.email = ADDRESS
        self.user.save()
        self.client = APIClient(enforce_csrf_checks=True)
        self.enable_email_codes()

    def start(self):
        self.login()
        return self.post("/api/auth/mfa/email/send")

    def test_login_offers_the_option_only_when_enabled(self):
        self.assertEqual(self.login().json(), {"mfa_required": True, "passkey_available": False, "email_code_available": True})

    def test_email_code_completes_login(self):
        sent = self.start()
        self.assertEqual((sent.status_code, sent.json()), (200, {"sent_to": "a***@example.test"}))
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)  # still signed out
        response = self.post("/api/auth/mfa/email/verify", {"code": last_code()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mfa_method"], "email")
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)
        self.assertEqual(self.client.get("/api/workspaces/").status_code, 200)

    def test_code_works_once(self):
        self.start()
        code = last_code()
        self.assertEqual(self.post("/api/auth/mfa/email/verify", {"code": code}).status_code, 200)
        self.post("/api/auth/logout")
        self.login()
        response = self.post("/api/auth/mfa/email/verify", {"code": code})
        self.assertEqual((response.status_code, response.json()["code"]), (401, "email_code_invalid"))

    def test_wrong_code_is_refused(self):
        self.start()
        wrong = "000000" if last_code() != "000000" else "111111"
        response = self.post("/api/auth/mfa/email/verify", {"code": wrong})
        self.assertEqual((response.status_code, response.json()["code"]), (401, "email_code_invalid"))
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_five_wrong_guesses_burn_the_code(self):
        self.start()
        code = last_code()
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(email_codes.MAX_ATTEMPTS_PER_CODE):
            self.post("/api/auth/mfa/email/verify", {"code": wrong})
        self.assertEqual(self.post("/api/auth/mfa/email/verify", {"code": code}).status_code, 401)

    def test_expired_code_is_refused(self):
        self.start()
        EmailCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.post("/api/auth/mfa/email/verify", {"code": last_code()}).status_code, 401)

    def test_a_new_code_replaces_the_old_one(self):
        self.start()
        first = last_code()
        self.backdate_sends(120)
        self.assertEqual(self.post("/api/auth/mfa/email/send").status_code, 200)
        second = last_code()
        if first != second:
            self.assertEqual(self.post("/api/auth/mfa/email/verify", {"code": first}).status_code, 401)
        self.assertEqual(self.post("/api/auth/mfa/email/verify", {"code": second}).status_code, 200)

    def test_resend_cooldown_and_hourly_cap(self):
        self.assertEqual(self.start().status_code, 200)
        soon = self.post("/api/auth/mfa/email/send")
        self.assertEqual((soon.status_code, soon.json()["code"]), (429, "email_code_wait"))
        self.assertIn("Retry-After", soon)
        self.assertEqual(len(mail.outbox), 1)
        for _ in range(email_codes.MAX_SENDS_PER_HOUR - 1):
            self.backdate_sends(120)  # past the cooldown, still inside the hour
            self.assertEqual(self.post("/api/auth/mfa/email/send").status_code, 200)
        capped = self.post("/api/auth/mfa/email/send")
        self.assertEqual((capped.status_code, capped.json()["code"]), (429, "email_code_wait"))

    @override_settings(MFA_LOCKOUT_THRESHOLD=2)
    def test_wrong_codes_count_toward_the_lockout(self):
        self.start()
        wrong = "000000" if last_code() != "000000" else "111111"
        for _ in range(2):
            self.post("/api/auth/mfa/email/verify", {"code": wrong})
        locked = self.post("/api/auth/mfa/email/verify", {"code": last_code()})
        self.assertEqual((locked.status_code, locked.json()["code"]), (403, "mfa_locked"))
        self.backdate_sends()
        resend = self.post("/api/auth/mfa/email/send")
        self.assertEqual((resend.status_code, resend.json()["code"]), (403, "mfa_locked"))
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_an_enrolment_code_cannot_sign_in(self):
        self.sign_in_with_code(self.secret)
        self.assertEqual(self.post("/api/account/mfa/email/begin").status_code, 200)
        enable_code = last_code()
        self.post("/api/auth/logout")
        self.login()
        response = self.post("/api/auth/mfa/email/verify", {"code": enable_code})
        self.assertEqual(response.status_code, 401)

    def test_codes_go_to_the_confirmed_address_even_if_the_profile_changes(self):
        self.user.email = "someone-else@example.test"
        self.user.save()
        self.start()
        self.assertEqual(mail.outbox[-1].to, [ADDRESS])

    def test_no_pending_login(self):
        self.assertEqual(self.post("/api/auth/mfa/email/send").json()["code"], "mfa_session_expired")
        verify = self.post("/api/auth/mfa/email/verify", {"code": "123456"})
        self.assertEqual((verify.status_code, verify.json()["code"]), (401, "mfa_session_expired"))

    def test_account_that_never_opted_in(self):
        MfaDevice.objects.update(email_codes_address="")
        self.login()
        response = self.post("/api/auth/mfa/email/send")
        self.assertEqual((response.status_code, response.json()["code"]), (400, "email_codes_not_enabled"))
        self.assertEqual(mail.outbox, [])

    @override_settings(MFA_EMAIL_CODES_ENABLED=False)
    def test_switched_off_server_wide(self):
        self.assertFalse(self.login().json()["email_code_available"])
        response = self.post("/api/auth/mfa/email/send")
        self.assertEqual((response.status_code, response.json()["code"]), (404, "email_codes_unavailable"))

    def test_bad_input_is_validated(self):
        self.start()
        for body in ({}, {"code": ""}, {"code": "x" * 33}):
            self.assertEqual(self.post("/api/auth/mfa/email/verify", body).status_code, 400)

    def test_authenticator_code_still_works_alongside(self):
        self.login()
        next_step = totp.totp_at(self.secret, time.time() + 30)  # the setup code already used this step
        response = self.post("/api/auth/mfa/verify", {"code": next_step})
        self.assertEqual((response.status_code, response.json()["mfa_method"]), (200, "totp"))


class HelperTests(TestCase):
    def test_mask(self):
        self.assertEqual(email_codes.mask("alice@example.test"), "a***@example.test")
        self.assertEqual(email_codes.mask("nonsense"), "***")

    def test_availability_needs_both_settings(self):
        with override_settings(MFA_EMAIL_CODES_ENABLED=True, MFA_EMAIL_FROM=""):
            self.assertFalse(email_codes.available())
        with override_settings(MFA_EMAIL_CODES_ENABLED=False, MFA_EMAIL_FROM="a@b.test"):
            self.assertFalse(email_codes.available())
        with override_settings(**EMAIL_SETTINGS):
            self.assertTrue(email_codes.available())
