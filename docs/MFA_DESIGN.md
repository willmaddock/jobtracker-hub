# MFA and account security design

Status: **decisions taken by the project owner's delegation; stages 1 (primitives) and 2 (models, key, service) implemented.**
Not yet recorded in `DJANGO_MIGRATION_DECISIONS.md`.

## Decisions
1. **Method:** authenticator-app TOTP (RFC 6238; SHA-1, 6 digits, 30 s, +/-1 step) plus 10
   single-use recovery codes. Passkeys (WebAuthn) are a later addition. **SMS and email codes were
   originally excluded** (SIM-swap and mailbox-takeover risk, and the product sent no email). Stage 7
   adds emailed codes as an optional, opt-in, off-by-default fallback; see its section for the trade-off.
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
2. Models and migration: `MfaDevice` (encrypted secret, confirmed flag, last step, failure counter,
   lock), `MfaRecoveryCode`; `accounts/mfa.py` service; `MFA_ENCRYPTION_KEY` admission in `prod.py`
   (a fourth distinct Fernet key) and its tests. *Done (pending first test run).*
3. Login flow endpoints, enforcement (DRF permission plus admin guard), throttling, tests.
4. Frontend: sign-in code step, enrolment (QR + recovery codes), settings, admin MFA reset.
5. Product admin role and user management.

## Explicitly not covered yet
Passkeys, trusted-device ("remember this browser") cookies, step-up re-authentication for sensitive
actions, and audit-log export.

## Stage 3: login flow, enforcement, throttling

- `POST /api/auth/login` returns `{"mfa_required": true}` for an enrolled user and creates **no** session; the password is parked in a 5-minute server-side pending marker. `POST /api/auth/mfa/verify` (code or recovery code) creates the session.
- With `MFA_REQUIRED` (forced on in production, off in dev/tests) an unenrolled user gets a restricted session (`mfa_enrollment_required`) that can only enrol or log out.
- `accounts.middleware.MfaEnforcementMiddleware` refuses `/api/*` (except `/api/auth/*`, `/api/health`) and `/admin/` to any session not marked verified, so Django's own admin login is no bypass. Admin sessions redirect to `/`, where the app must show the code prompt.
- Login and code endpoints are throttled per client IP (10/min in production); the per-account lockout in `accounts.mfa` remains the stronger control. The per-process cache makes the IP limit per worker until a shared cache (Redis) is configured.
- Operator reset: delete the user's row under Admin > Mfa devices. Secrets and codes are never displayed.

## Stage 6: passkeys (WebAuthn)

- A passkey is an additional second factor, offered at the code prompt and managed under Security. It can only be added after the authenticator app and recovery codes exist, and passkey rows belong to that MFA record, so an operator reset removes them with it.
- User verification (Face ID, Touch ID, device PIN) is required on every registration and sign-in. Attestation is not requested.
- Challenges are stored in the server session, single use, and expire after 5 minutes. The relying-party id and origin come from `WEBAUTHN_RP_ID` / `WEBAUTHN_ORIGIN`, never from the request. Production validates they describe the same https site; unset disables passkeys.
- Signature counters are stored and checked by the library. A locked account refuses passkeys as it refuses codes. At most 10 passkeys per account.
- All library calls live in `accounts/passkeys.py`. Changing the site's domain invalidates registered passkeys.

## Stage 7: emailed codes (optional, off by default)

- **Trade-off, accepted deliberately:** an emailed code is weaker than an authenticator app or passkey, because anyone who controls the mailbox and knows the password can sign in. It is therefore a per-user opt-in on top of the authenticator app, and the operator switch is off unless `MFA_EMAIL_CODES_ENABLED=true`. Leave it off in production unless the fallback is needed; recovery codes and passkeys already cover a lost authenticator.
- **Enabling:** from Security (verified session only), after the authenticator app and recovery codes exist. A code is emailed to the account's address and must be entered back. The confirmed address is stored on the MFA record, so later edits to the profile email never redirect codes. An operator MFA reset removes it with the rest.
- **Sign-in:** the code prompt offers "Email me a code" when the user has opted in. The code completes the same pending login as an authenticator code or passkey.
- **Code rules:** six digits, stored only as a salted keyed hash (HMAC-SHA256 with `SECRET_KEY`), valid 10 minutes, single use, 5 guesses per code, 60 s between emails, at most 5 emails an hour per account. A newer code replaces older ones. Enrolment codes cannot sign in.
- **Lockout:** wrong emailed sign-in codes count toward the same account lockout as authenticator codes, and a locked account gets no email and no acceptance.
- **Mail delivery:** production needs `MFA_EMAIL_FROM` and an SMTP relay (`EMAIL_SMTP_HOST`, port, TLS, credentials; for AWS SES, its SMTP endpoint and SMTP credentials). Enabling with any of that missing or malformed refuses to start. A send failure leaves no usable code and tells the user to try later. Locally, the compose stack runs Mailpit; read mail at http://localhost:8025.
- **Still not covered:** SMS codes (needs a texting provider and US carrier registration).

## Stage 8: passwordless sign-in and sign-up by emailed code (proposed by the project owner, 2026-11-06)

Surfaced for review, not a silent rewrite: this changes decision 1 above ("SMS and email codes are
deliberately excluded") and decision 2 ("no opt-out in production"), which stage 7 already softened for the
*second* step. Stage 8 lets an emailed code be the *first* step, replacing the password.

* **Where:** `accounts/email_signin.py`, `email_signin_views.py`; endpoints `GET /api/auth/options`,
  `POST /api/auth/email/start`, `POST /api/auth/email/verify`. New table `SignInCode`.
* **Off by default.** `EMAIL_SIGNIN_ENABLED` (and a mail sender) turns it on; `EMAIL_SIGNUP_OPEN` lets an unknown
  address create an account (with one empty workspace, "My job search"); production reads the same names from
  the environment and refuses to start if sign-in is on without mail settings.
* **No downgrade.** An account with an authenticator app is still asked for it after the emailed code. Staff and
  superuser accounts without an authenticator cannot use it at all.
* **MFA_REQUIRED decision (open):** with `MFA_REQUIRED=true` and `EMAIL_SIGNIN_SATISFIES_MFA=false` (the default),
  an account with no authenticator is signed in but must enrol one, so passwordless sign-in does nothing for
  ordinary users. Setting `EMAIL_SIGNIN_SATISFIES_MFA=true` accepts the emailed code as the only factor for
  accounts that have no authenticator. The local compose file sets it to true; production does not unless the
  operator does. Accepting this is a security trade-off: control of the mailbox is control of the account.
* **No account enumeration:** the start endpoint answers and rate-limits identically whether or not the address
  can sign in. Codes: 6 digits, keyed salted hash, 10 minutes, single use, 5 guesses, 60 s resend, 5 emails/hour
  per address, plus a per-IP throttle (`email_signin`).
* **Not in stage 8:** Google and Apple sign-in, phone/SMS, importing existing local data, account deletion.
