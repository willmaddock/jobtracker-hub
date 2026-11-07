"""RFC test vectors and misuse cases for accounts.totp. Pure unittest: no database."""
import base64
import unittest

from accounts import totp

RFC_SECRET = base64.b32encode(b"12345678901234567890").decode().rstrip("=")


class TotpVectorTests(unittest.TestCase):
    def test_rfc4226_hotp_vectors(self):
        key = b"12345678901234567890"
        expected = ["755224", "287082", "359152", "969429", "338314",
                    "254676", "287922", "162583", "399871", "520489"]
        self.assertEqual([totp._hotp(key, n) for n in range(10)], expected)

    def test_rfc6238_sha1_vectors_six_digits(self):
        # RFC 6238 Appendix B (SHA-1), last six of the published 8-digit values.
        for when, code in ((59, "287082"), (1111111109, "081804"), (1111111111, "050471"),
                           (1234567890, "005924"), (2000000000, "279037"), (20000000000, "353130")):
            with self.subTest(when=when):
                self.assertEqual(totp.totp_at(RFC_SECRET, when), code)


class VerifyTotpTests(unittest.TestCase):
    NOW = 1234567890

    def test_accepts_current_and_adjacent_steps_only(self):
        for offset, ok in ((-2, False), (-1, True), (0, True), (1, True), (2, False)):
            code = totp.totp_at(RFC_SECRET, self.NOW + offset * 30)
            got = totp.verify_totp(RFC_SECRET, code, now=self.NOW)
            self.assertEqual(got is not None, ok, offset)

    def test_returns_the_matched_step(self):
        code = totp.totp_at(RFC_SECRET, self.NOW)
        self.assertEqual(totp.verify_totp(RFC_SECRET, code, now=self.NOW), self.NOW // 30)

    def test_replay_is_refused(self):
        code = totp.totp_at(RFC_SECRET, self.NOW)
        step = totp.verify_totp(RFC_SECRET, code, now=self.NOW)
        self.assertIsNone(totp.verify_totp(RFC_SECRET, code, now=self.NOW, last_used_step=step))
        # An older step is also refused once a newer one was used.
        older = totp.totp_at(RFC_SECRET, self.NOW - 30)
        self.assertIsNone(totp.verify_totp(RFC_SECRET, older, now=self.NOW, last_used_step=step))

    def test_next_step_is_still_accepted_after_a_use(self):
        used = self.NOW // 30 - 1
        code = totp.totp_at(RFC_SECRET, self.NOW)
        self.assertEqual(totp.verify_totp(RFC_SECRET, code, now=self.NOW, last_used_step=used), self.NOW // 30)

    def test_malformed_codes_are_refused(self):
        good = totp.totp_at(RFC_SECRET, self.NOW)
        for bad in ("", "12345", "1234567", "abcdef", "12 34", None, 123456, good + " x", "１２３４５６"):
            with self.subTest(bad=bad):
                self.assertIsNone(totp.verify_totp(RFC_SECRET, bad, now=self.NOW))
        self.assertIsNotNone(totp.verify_totp(RFC_SECRET, f"{good[:3]} {good[3:]}", now=self.NOW))

    def test_wrong_secret_is_refused(self):
        other = totp.generate_secret()
        code = totp.totp_at(other, self.NOW)
        self.assertIsNone(totp.verify_totp(RFC_SECRET, code, now=self.NOW))


class SecretAndUriTests(unittest.TestCase):
    def test_secret_shape_and_uniqueness(self):
        a, b = totp.generate_secret(), totp.generate_secret()
        self.assertNotEqual(a, b)
        self.assertEqual(len(a), 32)
        self.assertEqual(len(base64.b32decode(a)), 20)
        self.assertNotIn("=", a)

    def test_spaced_lowercase_secret_still_decodes(self):
        spaced = " ".join(RFC_SECRET[i:i + 4] for i in range(0, len(RFC_SECRET), 4)).lower()
        self.assertEqual(totp.totp_at(spaced, 59), totp.totp_at(RFC_SECRET, 59))

    def test_provisioning_uri(self):
        uri = totp.provisioning_uri("ABC234", "will@example.com", "JobTracker Hub")
        self.assertTrue(uri.startswith("otpauth://totp/JobTracker%20Hub%3Awill%40example.com?"))
        for part in ("secret=ABC234", "issuer=JobTracker%20Hub", "algorithm=SHA1", "digits=6", "period=30"):
            self.assertIn(part, uri)


class RecoveryCodeTests(unittest.TestCase):
    def test_generation_shape(self):
        codes = totp.generate_recovery_codes()
        self.assertEqual(len(codes), 10)
        self.assertEqual(len(set(codes)), 10)
        for code in codes:
            self.assertRegex(code, r"^[A-HJ-NP-Z2-9]{5}-[A-HJ-NP-Z2-9]{5}$")

    def test_hash_roundtrip_and_normalisation(self):
        code = "K7QX2-M9PTD"
        stored = totp.hash_recovery_code(code)
        self.assertTrue(stored.startswith("pbkdf2_sha256$120000$"))
        self.assertNotIn("K7QX2", stored)
        for variant in (code, "k7qx2-m9ptd", "K7QX2M9PTD", " K7QX2 M9PTD "):
            self.assertTrue(totp.check_recovery_code(variant, stored), variant)
        self.assertFalse(totp.check_recovery_code("K7QX2-M9PTE", stored))

    def test_salts_differ(self):
        self.assertNotEqual(totp.hash_recovery_code("K7QX2-M9PTD"), totp.hash_recovery_code("K7QX2-M9PTD"))

    def test_malformed_stored_values_fail_closed(self):
        for stored in ("", "plain", "sha1$1$a$b", "pbkdf2_sha256$x$a$b", "pbkdf2_sha256$1$a"):
            with self.subTest(stored=stored):
                self.assertFalse(totp.check_recovery_code("K7QX2-M9PTD", stored))


if __name__ == "__main__":
    unittest.main()
