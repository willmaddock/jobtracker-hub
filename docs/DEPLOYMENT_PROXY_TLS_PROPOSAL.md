# Proposal: TLS-terminating proxy support (NOT ACCEPTED)

This is a proposal for review. It does not change `DJANGO_MIGRATION_DECISIONS.md` and
no settings were changed. Status calls "trusted proxy topology" an open gate.

## Problem
`prod.py` sets `SECURE_SSL_REDIRECT = True`, `SECURE_PROXY_SSL_HEADER = None` and rejects
`DJANGO_CSRF_TRUSTED_ORIGINS`. With TLS ending at an AWS ALB (or CloudFront), the container
receives plain HTTP, so Django:
- redirects every request to HTTPS forever (redirect loop), and
- would, once reachable, treat requests as insecure, so HTTPS `Origin` headers fail CSRF
  origin checks.

## Proposed option (A): ALB terminates TLS, trust `X-Forwarded-Proto`
Add one explicit opt-in, default OFF (current fail-closed behaviour unchanged):
`DJANGO_BEHIND_TLS_PROXY=true` -> `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`.
`USE_X_FORWARDED_HOST/PORT` stay False. Same-origin means `CSRF_TRUSTED_ORIGINS` is still not needed.

Required infrastructure conditions (must hold, or the header can be spoofed):
- Containers reachable only from the ALB security group, never directly from the internet.
- ALB sets `X-Forwarded-Proto` (it does); no other hop in front is untrusted.

Gotchas to verify in staging:
- ALB health checks go to the target over HTTP: `SECURE_SSL_REDIRECT` would answer 301.
  Exempt `/api/health` (`SECURE_REDIRECT_EXEMPT`) or accept 200-399 on the target group.
- Health checks use the task IP as `Host`, which `ALLOWED_HOSTS` rejects (400). Needs a
  small pre-host-validation health responder or an explicit allowance.

## Alternatives
- (B) TLS terminated inside the container / NLB passthrough: no header trust, but certificate
  management in the app tier. More operational work.
- (C) CloudFront in front of the ALB: same header question, plus cache/CSRF-cookie rules.

## Decision requested
Approve (A), then implementation + tests (setting off by default, on with the env var,
health exemption, spoofed-header behaviour) will follow as a separate reviewed change.
