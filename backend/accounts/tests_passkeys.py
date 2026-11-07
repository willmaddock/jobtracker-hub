"""Passkey registration and sign-in over real cookie sessions.

The WebAuthn signature checks belong to the ``webauthn`` library and need a real authenticator, so
the flow tests replace just those two verification calls (``_verify_registration`` and
``_verify_authentication``). Challenge handling, ownership, lockout, counters, sessions and the
MFA gate are all real. ``RealLibraryOptionsTests`` runs the library's option generation unmocked.
"""
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from . import mfa, passkeys
from .models import MfaDevice, PasskeyCredential, User
from .tests_mfa_login import HttpMixin, PW, make_enrolled

CRED_ID = "Y3JlZC0x"  # base64url of b"cred-1"
PASSKEY_SETTINGS = dict(WEBAUTHN_RP_ID="localhost", WEBAUTHN_ORIGIN="https://localhost:8443")
REGISTRATION = {"id": CRED_ID, "rawId": CRED_ID, "type": "public-key", "response": {}}


def verified_registration(raw=b"cred-1"):
    return SimpleNamespace(credential_id=raw, credential_public_key=b"public-key-bytes", sign_count=0)


class PasskeyMixin(HttpMixin):
    def delete(self, path, client=None):
        client = client or self.client
        token = client.get("/api/auth/csrf").data["csrfToken"]
        return client.delete(path, HTTP_X_CSRFTOKEN=token)

    def sign_in_with_code(self, secret, username="alice", client=None):
        client = client or self.client
        self.login(username, client)
        response = self.post("/api/auth/mfa/verify", {"code": self.code_now(secret)}, client)
        self.assertEqual(response.status_code, 200)

    def add_passkey(self, client=None, raw=b"cred-1"):
        """Register through the API (verification mocked) and return the new passkey id."""
        client = client or self.client
        self.assertEqual(self.post("/api/account/passkeys/register/options", client=client).status_code, 200)
        with mock.patch("accounts.passkeys._verify_registration", return_value=verified_registration(raw)):
            response = self.post(
                "/api/account/passkeys/register/verify", {"credential": REGISTRATION, "name": "MacBook"}, client,
            )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()["id"]


@override_settings(**PASSKEY_SETTINGS)
class RegistrationTests(PasskeyMixin, TestCase):
    def setUp(self):
        self.user, self.secret, self.codes = make_enrolled()
        self.client = APIClient(enforce_csrf_checks=True)

    def test_register_list_and_remove(self):
        self.sign_in_with_code(self.secret)
        pk = self.add_passkey()
        listing = self.client.get("/api/account/passkeys/").json()
        self.assertTrue(listing["available"])
        self.assertEqual([(p["id"], p["name"]) for p in listing["passkeys"]], [(pk, "MacBook")])
        row = PasskeyCredential.objects.get(pk=pk)
        self.assertEqual(row.credential_id, CRED_ID)
        self.assertEqual(bytes(row.public_key), b"public-key-bytes")
        self.assertEqual(self.delete(f"/api/account/passkeys/{pk}/").status_code, 204)
        self.assertFalse(PasskeyCredential.objects.exists())

    def test_requires_a_signed_in_session(self):
        self.assertEqual(self.client.get("/api/account/passkeys/").status_code, 401)
        self.assertEqual(self.post("/api/account/passkeys/register/options").status_code, 401)

    @override_settings(MFA_REQUIRED=True)
    def test_unverified_session_cannot_manage_passkeys(self):
        self.client.force_login(self.user)  # password-only session, no code yet
        blocked = self.client.get("/api/account/passkeys/")
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.json()["code"], "mfa_required")
        self.assertEqual(self.post("/api/account/passkeys/register/options").status_code, 403)

    def test_needs_the_authenticator_app_first(self):
        User.objects.create_user(username="plain", password=PW)
        self.login("plain")
        for path, body in (("/api/account/passkeys/register/options", {}),
                           ("/api/account/passkeys/register/verify", {"credential": REGISTRATION})):
            response = self.post(path, body)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["code"], "mfa_not_enrolled")

    def test_challenge_is_single_use_and_required(self):
        self.sign_in_with_code(self.secret)
        with mock.patch("accounts.passkeys._verify_registration", return_value=verified_registration()) as verify:
            response = self.post("/api/account/passkeys/register/verify", {"credential": REGISTRATION})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["code"], "passkey_challenge_invalid")
            self.assertFalse(verify.called)  # no challenge issued: nothing is verified
        self.add_passkey()
        with mock.patch("accounts.passkeys._verify_registration", return_value=verified_registration(b"cred-2")):
            again = self.post("/api/account/passkeys/register/verify", {"credential": REGISTRATION})
        self.assertEqual(again.json()["code"], "passkey_challenge_invalid")

    def test_expired_challenge_is_refused(self):
        self.sign_in_with_code(self.secret)
        self.post("/api/account/passkeys/register/options")
        session = self.client.session
        stored = session[passkeys.CHALLENGE_KEY]
        stored["ts"] -= 1000
        session[passkeys.CHALLENGE_KEY] = stored
        session.save()
        with mock.patch("accounts.passkeys._verify_registration", return_value=verified_registration()):
            response = self.post("/api/account/passkeys/register/verify", {"credential": REGISTRATION})
        self.assertEqual(response.json()["code"], "passkey_challenge_invalid")

    def test_rejected_attestation_creates_nothing(self):
        self.sign_in_with_code(self.secret)
        self.post("/api/account/passkeys/register/options")
        with mock.patch("accounts.passkeys._verify_registration", side_effect=passkeys.InvalidCredential()):
            response = self.post("/api/account/passkeys/register/verify", {"credential": REGISTRATION})
        self.assertEqual((response.status_code, response.json()["code"]), (400, "passkey_invalid"))
        self.assertFalse(PasskeyCredential.objects.exists())

    def test_same_credential_cannot_be_registered_twice(self):
        self.sign_in_with_code(self.secret)
        self.add_passkey()
        self.post("/api/account/passkeys/register/options")
        with mock.patch("accounts.passkeys._verify_registration", return_value=verified_registration()):
            response = self.post("/api/account/passkeys/register/verify", {"credential": REGISTRATION})
        self.assertEqual(response.json()["code"], "passkey_invalid")
        self.assertEqual(PasskeyCredential.objects.count(), 1)

    def test_input_is_validated(self):
        self.sign_in_with_code(self.secret)
        for body in ({}, {"credential": "not-an-object"}, {"credential": REGISTRATION, "name": "x" * 81}):
            self.assertEqual(self.post("/api/account/passkeys/register/verify", body).status_code, 400)

    def test_limit_per_account(self):
        self.sign_in_with_code(self.secret)
        device = MfaDevice.objects.get(user=self.user)
        for i in range(passkeys.MAX_PASSKEYS_PER_DEVICE):
            PasskeyCredential.objects.create(device=device, credential_id=f"id{i}", public_key=b"k", name="k")
        response = self.post("/api/account/passkeys/register/options")
        self.assertEqual((response.status_code, response.json()["code"]), (409, "passkey_limit_reached"))

    def test_other_users_passkeys_are_invisible_and_undeletable(self):
        self.sign_in_with_code(self.secret)
        pk = self.add_passkey()
        _bob, bob_secret, _codes = make_enrolled("bob")
        bob = APIClient(enforce_csrf_checks=True)
        self.sign_in_with_code(bob_secret, "bob", bob)
        self.assertEqual(bob.get("/api/account/passkeys/").json()["passkeys"], [])
        self.assertEqual(self.delete(f"/api/account/passkeys/{pk}/", bob).status_code, 404)
        self.assertEqual(PasskeyCredential.objects.count(), 1)

    def test_operator_reset_removes_passkeys(self):
        self.sign_in_with_code(self.secret)
        self.add_passkey()
        mfa.reset(self.user)
        self.assertFalse(PasskeyCredential.objects.exists())

    @override_settings(WEBAUTHN_RP_ID="", WEBAUTHN_ORIGIN="")
    def test_unavailable_when_not_configured(self):
        self.sign_in_with_code(self.secret)
        response = self.post("/api/account/passkeys/register/options")
        self.assertEqual((response.status_code, response.json()["code"]), (404, "passkeys_unavailable"))
        self.assertFalse(self.client.get("/api/account/passkeys/").json()["available"])


@override_settings(**PASSKEY_SETTINGS)
class SignInTests(PasskeyMixin, TestCase):
    def setUp(self):
        self.user, self.secret, self.codes = make_enrolled()
        self.device = MfaDevice.objects.get(user=self.user)
        self.row = PasskeyCredential.objects.create(
            device=self.device, credential_id=CRED_ID, public_key=b"public-key-bytes", sign_count=3, name="MacBook",
        )
        self.client = APIClient(enforce_csrf_checks=True)
        self.assertion = {"id": CRED_ID, "rawId": CRED_ID, "type": "public-key", "response": {}}

    def start(self):
        self.assertEqual(self.login().json(), {"mfa_required": True, "passkey_available": True})
        response = self.post("/api/auth/mfa/passkey/options")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_passkey_completes_login_and_updates_counter(self):
        options = self.start()
        self.assertEqual([c["id"] for c in options["allowCredentials"]], [CRED_ID])
        self.assertEqual(options["userVerification"], "required")
        self.assertEqual(self.client.get("/api/workspaces/").status_code, 401)
        with mock.patch("accounts.passkeys._verify_authentication", return_value=SimpleNamespace(new_sign_count=9)) as verify:
            response = self.post("/api/auth/mfa/passkey/verify", {"credential": self.assertion})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["mfa_method"], "passkey")
        self.assertEqual(verify.call_args.kwargs["sign_count"], 3)
        self.assertEqual(verify.call_args.kwargs["public_key"], b"public-key-bytes")
        self.row.refresh_from_db()
        self.assertEqual(self.row.sign_count, 9)
        self.assertIsNotNone(self.row.last_used_at)
        self.assertEqual(self.client.get("/api/workspaces/").status_code, 200)

    def test_challenge_is_single_use(self):
        self.start()
        with mock.patch("accounts.passkeys._verify_authentication", return_value=SimpleNamespace(new_sign_count=4)):
            self.assertEqual(self.post("/api/auth/mfa/passkey/verify", {"credential": self.assertion}).status_code, 200)
            self.post("/api/auth/logout")
            self.login()
            replay = self.post("/api/auth/mfa/passkey/verify", {"credential": self.assertion})
        self.assertEqual((replay.status_code, replay.json()["code"]), (400, "passkey_challenge_invalid"))
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_rejected_assertion_keeps_signed_out(self):
        self.start()
        with mock.patch("accounts.passkeys._verify_authentication", side_effect=passkeys.InvalidCredential()):
            response = self.post("/api/auth/mfa/passkey/verify", {"credential": self.assertion})
        self.assertEqual((response.status_code, response.json()["code"]), (401, "passkey_invalid"))
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.row.refresh_from_db()
        self.assertEqual(self.row.sign_count, 3)

    def test_unknown_credential_is_refused_without_verification(self):
        self.start()
        stranger = {**self.assertion, "id": "c3RyYW5nZXI"}
        with mock.patch("accounts.passkeys._verify_authentication") as verify:
            response = self.post("/api/auth/mfa/passkey/verify", {"credential": stranger})
        self.assertEqual((response.status_code, response.json()["code"]), (401, "passkey_invalid"))
        self.assertFalse(verify.called)

    def test_another_users_passkey_cannot_complete_this_login(self):
        _bob, _bob_secret, _codes = make_enrolled("bob")
        bob_device = MfaDevice.objects.get(user__username="bob")
        PasskeyCredential.objects.create(device=bob_device, credential_id="Ym9i", public_key=b"k", name="bob")
        self.start()
        with mock.patch("accounts.passkeys._verify_authentication") as verify:
            response = self.post("/api/auth/mfa/passkey/verify", {"credential": {**self.assertion, "id": "Ym9i"}})
        self.assertEqual(response.json()["code"], "passkey_invalid")
        self.assertFalse(verify.called)

    def test_without_a_pending_login(self):
        for path, body in (("/api/auth/mfa/passkey/options", {}),
                           ("/api/auth/mfa/passkey/verify", {"credential": self.assertion})):
            response = self.post(path, body)
            self.assertEqual((response.status_code, response.json()["code"]), (401, "mfa_session_expired"))

    def test_locked_account_refuses_passkeys_too(self):
        self.login()
        self.device.locked_at = self.device.created_at
        self.device.save()
        for path, body in (("/api/auth/mfa/passkey/options", {}),
                           ("/api/auth/mfa/passkey/verify", {"credential": self.assertion})):
            response = self.post(path, body)
            self.assertEqual((response.status_code, response.json()["code"]), (403, "mfa_locked"))

    def test_user_without_passkeys(self):
        make_enrolled("carol")
        self.assertEqual(self.login("carol").json(), {"mfa_required": True, "passkey_available": False})
        response = self.post("/api/auth/mfa/passkey/options")
        self.assertEqual((response.status_code, response.json()["code"]), (400, "passkey_not_registered"))

    def test_authenticator_code_still_works_alongside(self):
        self.start()
        response = self.post("/api/auth/mfa/verify", {"code": self.code_now(self.secret)})
        self.assertEqual(response.json()["mfa_method"], "totp")

    @override_settings(WEBAUTHN_RP_ID="", WEBAUTHN_ORIGIN="")
    def test_login_hides_passkeys_when_unavailable(self):
        self.assertEqual(self.login().json(), {"mfa_required": True, "passkey_available": False})


@override_settings(**PASSKEY_SETTINGS)
class RealLibraryOptionsTests(PasskeyMixin, TestCase):
    """Unmocked calls into the webauthn library: option generation only (no authenticator)."""

    def test_registration_and_authentication_options(self):
        user, secret, _codes = make_enrolled()
        self.client = APIClient(enforce_csrf_checks=True)
        self.sign_in_with_code(secret)
        reg = self.post("/api/account/passkeys/register/options")
        self.assertEqual(reg.status_code, 200, reg.content)
        body = reg.json()
        self.assertEqual(body["rp"]["id"], "localhost")
        self.assertEqual(body["authenticatorSelection"]["userVerification"], "required")
        self.assertEqual(body["user"]["name"], "alice")
        self.assertTrue(body["challenge"])
        self.add_passkey()
        self.post("/api/auth/logout")
        self.login()
        auth = self.post("/api/auth/mfa/passkey/options")
        self.assertEqual(auth.status_code, 200, auth.content)
        self.assertEqual(auth.json()["rpId"], "localhost")
        self.assertEqual(auth.json()["allowCredentials"][0]["id"], CRED_ID)
