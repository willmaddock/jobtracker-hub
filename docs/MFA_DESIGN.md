# MFA and account security design

Status: **decisions taken by the project owner's delegation; stage 1 (primitives) implemented.**
Not yet recorded in `DJANGO_MIGRATION_DECISIONS.md`.

## Decisions
1. **Method:** authenticator-app TOTP (RFC 6238; SHA-1, 6 digits, 30 s, +/-1 step) plus 10
   single-use recovery codes. Passkeys (WebAuthn) are a later addition. **SMS and email codes are
   deliberately excluded** (SIM-swap and mailbox-takeover risk, and the product sends no email).
2. **Who:** every account, including operators/admins. No opt-out in production.
3. **Enrolment:** a user who has never enrolled can sign in with their password, but every product
   API except enrolment and logout answers `mfa_enrollment_required` until a code is confirmed.
4. **Login flow:** password OK + enrolled -> no session yet, a short-lived "pending MFA" marker;
   `POST /api/auth/mfa/verify` with a code (or recovery code) completes the login. The session is
   rotated on completion.
5. **Replay:** the last accepted time step is stored per device; that step and earlier are refused.
6. **Secrets at rest:** the TOTP secret is encrypted (Fernet) with a dedicated key,
   `MFA_ENCRYPTION_KEY`, required and validated in production like the provider keys. Recovery codes
   are stored only as salted PBKDF2 hashes and shown once.
7. **Brute force:** per-user and per-IP throttling on password and code attempts; after repeated
   code failures the account locks until an operator resets it.
8. **Admin:** `/admin/` must not bypass MFA. A password-only admin session is refused until the same
   verification succeeds. Operators can reset a user's MFA from the admin (audited), never read
   secrets.
9. **Roles:** a product `admin` role (user management, MFA reset) is distinct from Django
   `is_superuser` (infrastructure operator). Built after MFA.

## Stages
1. **Primitives** (`accounts/totp.py`, tests against RFC vectors). *Done.*
2. Models and migration: `MfaDevice` (encrypted secret, confirmed flag, last step), recovery codes;
   `MFA_ENCRYPTION_KEY` admission in `prod.py` and its tests.
3. Login flow endpoints, enforcement (DRF permission plus admin guard), throttling, tests.
4. Frontend: sign-in code step, enrolment (QR + recovery codes), settings, admin MFA reset.
5. Product admin role and user management.

## Explicitly not covered yet
Passkeys, trusted-device ("remember this browser") cookies, step-up re-authentication for sensitive
actions, and audit-log export.
