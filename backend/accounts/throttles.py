"""IP-keyed throttles for sign-in and code entry, rates taken from settings.

``settings.AUTH_THROTTLE_RATES`` maps scope -> "N/period". A scope without a rate is not
throttled, so development and tests are unaffected; production sets real rates.
Counters live in the Django cache. With the default per-process cache each gunicorn worker
counts separately; a shared cache (Redis) makes the limit global. The per-account code
lockout in accounts.mfa is database-backed and is the stronger control.
"""
from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle


class _AuthThrottle(SimpleRateThrottle):
    def get_rate(self):
        return getattr(settings, "AUTH_THROTTLE_RATES", {}).get(self.scope)

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class LoginThrottle(_AuthThrottle):
    scope = "auth_login"


class MfaThrottle(_AuthThrottle):
    scope = "mfa"
