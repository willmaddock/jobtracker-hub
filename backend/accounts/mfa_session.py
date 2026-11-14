"""Session bookkeeping for the two-step login. See docs/MFA_DESIGN.md.

Two markers live in the server-side session (never in a cookie the client can edit):
``mfa_pending``  password accepted, code still required; the user is NOT logged in yet.
``mfa_verified`` this login session has proved possession of the second factor.
"""
from __future__ import annotations

import time

from django.contrib.auth import get_user_model

PENDING_KEY = "mfa_pending"
VERIFIED_KEY = "mfa_verified"
PENDING_TTL_SECONDS = 300


def start_pending(request, user) -> None:
    request.session.pop(VERIFIED_KEY, None)
    request.session[PENDING_KEY] = {"uid": user.pk, "ts": int(time.time())}


def pending_user(request):
    data = request.session.get(PENDING_KEY)
    if not isinstance(data, dict):
        return None
    try:
        if time.time() - int(data["ts"]) > PENDING_TTL_SECONDS:
            request.session.pop(PENDING_KEY, None)
            return None
        return get_user_model().objects.filter(pk=data["uid"], is_active=True).first()
    except (KeyError, TypeError, ValueError):
        request.session.pop(PENDING_KEY, None)
        return None


def clear_pending(request) -> None:
    request.session.pop(PENDING_KEY, None)


def mark_verified(request) -> None:
    request.session[VERIFIED_KEY] = True


def is_verified(request) -> bool:
    return request.session.get(VERIFIED_KEY) is True


def prepare_primary(request, user):
    """Gateway-only hook, after credentials were verified by the native flow."""
    state = getattr(request, 'gateway_lineage', None)
    if state is not None:
        state.prepare_primary(request, user)


def second_step_user(request):
    state = getattr(request, 'gateway_lineage', None)
    if state is not None:
        return state.factor_user(request)
    user = pending_user(request)
    return user if user is not None else request.user if request.user.is_authenticated else None


def check_completion(request, user):
    state = getattr(request, 'gateway_lineage', None)
    if state is not None:
        state.check_completion(request, user)


def assert_current_actor(request):
    state = getattr(request, 'gateway_lineage', None)
    if state is not None:
        state.assert_actor(request)
