"""MFA service tests: encrypted storage, replay, recovery codes, lockout, reset."""
from django.core.management import call_command
from django.test import TestCase, override_settings

from . import mfa, totp
from .models import MfaDevice, MfaRecoveryCode, User

NOW = 1234567890


def enrolled_user(name="mfa-user"):
    user = User.objects.create_user(username=name, password="correct horse battery staple")
    secret, _uri = mfa.begin_enrollment(user)
    codes = mfa.confirm_enrollment(user, totp.totp_at(secret, NOW), now=NOW)
    return user, secret, codes


class EnrollmentTests(TestCase):
    def test_secret_is_encrypted_at_rest(self):
        user = User.objects.create_user(username="a", password="x")
        secret, uri = mfa.begin_enrollment(user)
        stored = MfaDevice.objects.get(user=user).secret_encrypted
        self.assertNotEqual(stored, secret)
        self.assertNotIn(secret, stored)
        self.assertIn(f"secret={secret}", uri)
        self.assertIn("issuer=JobTracker%20Hub", uri)

    def test_unconfirmed_device_is_not_enrolled_and_cannot_verify(self):
        user = User.objects.create_user(username="a", password="x")
        secret, _ = mfa.begin_enrollment(user)
        self.assertFalse(mfa.is_enrolled(user))
        with self.assertRaises(mfa.NotEnrolled):
            mfa.verify_code(user, totp.totp_at(secret, NOW), now=NOW)

    def test_wrong_confirmation_code_does_not_enrol(self):
        user = User.objects.create_user(username="a", password="x")
        secret, _ = mfa.begin_enrollment(user)
        with self.assertRaises(mfa.InvalidCode):
            mfa.confirm_enrollment(user, "000000" if totp.totp_at(secret, NOW) != "000000" else "111111", now=NOW)
        self.assertFalse(mfa.is_enrolled(user))
        self.assertEqual(MfaRecoveryCode.objects.count(), 0)

    def test_confirmation_returns_ten_hashed_recovery_codes(self):
        user, _secret, codes = enrolled_user()
        self.assertTrue(mfa.is_enrolled(user))
        self.assertEqual(len(codes), 10)
        self.assertEqual(mfa.remaining_recovery_codes(user), 10)
        stored = " ".join(MfaRecoveryCode.objects.values_list("code_hash", flat=True))
        for code in codes:
            self.assertNotIn(code.replace("-", ""), stored)

    def test_restart_before_confirmation_replaces_secret_but_confirmed_is_protected(self):
        user = User.objects.create_user(username="a", password="x")
        first, _ = mfa.begin_enrollment(user)
        second, _ = mfa.begin_enrollment(user)
        self.assertNotEqual(first, second)
        mfa.confirm_enrollment(user, totp.totp_at(second, NOW), now=NOW)
        with self.assertRaises(mfa.AlreadyEnrolled):
            mfa.begin_enrollment(user)
        with self.assertRaises(mfa.AlreadyEnrolled):
            mfa.confirm_enrollment(user, totp.totp_at(second, NOW + 30), now=NOW + 30)


class VerificationTests(TestCase):
    def test_totp_accepted_once_then_replay_refused(self):
        user, secret, _ = enrolled_user()
        later = NOW + 60
        code = totp.totp_at(secret, later)
        self.assertEqual(mfa.verify_code(user, code, now=later), "totp")
        with self.assertRaises(mfa.InvalidCode):
            mfa.verify_code(user, code, now=later)

    def test_enrolment_code_cannot_be_replayed_to_log_in(self):
        user, secret, _ = enrolled_user()
        with self.assertRaises(mfa.InvalidCode):
            mfa.verify_code(user, totp.totp_at(secret, NOW), now=NOW)

    def test_recovery_code_is_single_use(self):
        user, _secret, codes = enrolled_user()
        self.assertEqual(mfa.verify_code(user, codes[0], now=NOW), "recovery")
        self.assertEqual(mfa.remaining_recovery_codes(user), 9)
        with self.assertRaises(mfa.InvalidCode):
            mfa.verify_code(user, codes[0], now=NOW)
        self.assertEqual(mfa.verify_code(user, codes[1].lower(), now=NOW), "recovery")

    def test_other_users_codes_do_not_work(self):
        user, _s, _c = enrolled_user("one")
        other, other_secret, other_codes = enrolled_user("two")
        with self.assertRaises(mfa.InvalidCode):
            mfa.verify_code(user, other_codes[0], now=NOW)
        with self.assertRaises(mfa.InvalidCode):
            mfa.verify_code(user, totp.totp_at(other_secret, NOW + 60), now=NOW + 60)

    def test_unenrolled_user(self):
        user = User.objects.create_user(username="plain", password="x")
        with self.assertRaises(mfa.NotEnrolled):
            mfa.verify_code(user, "123456", now=NOW)

    @override_settings(MFA_LOCKOUT_THRESHOLD=3)
    def test_failures_are_persisted_and_lock_the_account(self):
        user, secret, _ = enrolled_user()
        for expected in (1, 2):
            with self.assertRaises(mfa.InvalidCode):
                mfa.verify_code(user, "000000", now=NOW + 60)
            self.assertEqual(MfaDevice.objects.get(user=user).failed_attempts, expected)  # survived the raise
        with self.assertRaises(mfa.InvalidCode):
            mfa.verify_code(user, "000000", now=NOW + 60)
        device = MfaDevice.objects.get(user=user)
        self.assertEqual(device.failed_attempts, 3)
        self.assertIsNotNone(device.locked_at)
        with self.assertRaises(mfa.Locked):  # even a correct code is refused
            mfa.verify_code(user, totp.totp_at(secret, NOW + 90), now=NOW + 90)

    @override_settings(MFA_LOCKOUT_THRESHOLD=3)
    def test_success_resets_the_failure_counter(self):
        user, secret, _ = enrolled_user()
        for _ in range(2):
            with self.assertRaises(mfa.InvalidCode):
                mfa.verify_code(user, "000000", now=NOW + 60)
        mfa.verify_code(user, totp.totp_at(secret, NOW + 60), now=NOW + 60)
        self.assertEqual(MfaDevice.objects.get(user=user).failed_attempts, 0)

    def test_reset_clears_everything_and_allows_reenrolment(self):
        user, _s, _c = enrolled_user()
        mfa.reset(user)
        self.assertFalse(mfa.is_enrolled(user))
        self.assertEqual(MfaDevice.objects.count(), 0)
        self.assertEqual(MfaRecoveryCode.objects.count(), 0)
        mfa.begin_enrollment(user)


class SchemaTests(TestCase):
    def test_models_and_migrations_are_in_sync(self):
        # Exits non-zero (SystemExit) if a model change lacks a migration.
        call_command("makemigrations", "accounts", "--check", "--dry-run", verbosity=0)
