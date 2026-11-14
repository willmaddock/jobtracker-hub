"""Stable authority and request-scoped native hooks.

One default-database transaction owns native session writes and the authority
update. This module never authenticates from a lineage identifier or context.
"""
from datetime import timedelta
import time
from django.conf import settings
from django.contrib.auth import get_user_model, logout
from django.contrib.sessions.models import Session
from django.core import signing
from django.core.exceptions import ImproperlyConfigured
from django.db import DEFAULT_DB_ALIAS, connection, models, router
from django.utils import timezone
from accounts import mfa_session
from . import session_context as context
from .models import GatewaySessionLineage

DB = DEFAULT_DB_ALIAS


class BoundaryError(Exception):
    def __init__(self, code='gateway_principal_changed', status=409):
        self.code, self.status = code, status


def check_configuration():
    if (settings.SESSION_ENGINE != 'django.contrib.sessions.backends.db'
            or settings.SESSION_SAVE_EVERY_REQUEST or settings.DATABASE_ROUTERS):
        raise ImproperlyConfigured('Gateway lineage requires default-database Django DB sessions, no database routers, and SESSION_SAVE_EVERY_REQUEST=False.')
    for model in (Session, GatewaySessionLineage):
        if router.db_for_write(model) != DB or router.db_for_read(model) != DB:
            raise ImproperlyConfigured('Gateway session and lineage must use the same default database.')


def lock(pk):
    if not connection.in_atomic_block or connection.alias != DB:
        raise RuntimeError('Lineage lock requires its owning default-database transaction.')
    rows = GatewaySessionLineage.objects.using(DB).filter(pk=pk)
    if connection.vendor == 'sqlite':
        rows.update(generation=models.F('generation'))
        return rows.first()
    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '5s'")
    return rows.select_for_update().first()


def cookie_id(request):
    token = request.COOKIES.get(context.cookie_name(), '')
    try:
        value = signing.loads(token, salt=context.COOKIE_SALT, max_age=settings.SESSION_COOKIE_AGE)
        from uuid import UUID
        return UUID(value) if isinstance(value, str) else None
    except (signing.BadSignature, ValueError, TypeError):
        return None


def fresh():
    return GatewaySessionLineage.objects.using(DB).create(
        expires_at=timezone.now() + timedelta(seconds=settings.SESSION_COOKIE_AGE))


def recovery(row):
    return signing.dumps({'v': 2, 'purpose': 'restart', 'l': str(row.pk), 'g': str(row.generation)}, salt=context.RECOVERY_SALT)


def valid_recovery(request, row):
    try:
        value = signing.loads(request.headers.get('X-JTH-Recovery', ''), salt=context.RECOVERY_SALT, max_age=300)
    except signing.BadSignature:
        return False
    return value == {'v': 2, 'purpose': 'restart', 'l': str(row.pk), 'g': str(row.generation)}


def prune_expired():
    # Scheduling is an explicit hosting task. Never prune active lineages.
    return GatewaySessionLineage.objects.using(DB).filter(expires_at__lte=timezone.now()).delete()[0]


class Binding:
    def __init__(self, row, *, writing, bootstrap=False, recovery_request=False):
        self.row, self.writing, self.bootstrap = row, writing, bootstrap
        self.recovery_request = recovery_request
        self.rejected = False
        self.new_attempt = False
        self.prepared = False
        self.saved = False
        self.primary_target = None
        self.kind = 'other'
        self.before_key = row.session_key
        self.expected = None

    @property
    def generation(self):
        return self.row.generation + int(self.new_attempt)

    def reject(self, code='gateway_context_changed', status=409):
        self.rejected = True
        return context.conflict(code, status)

    def matches_session(self, request):
        return request.session.get(context.KEY) == {'l': str(self.row.pk), 'g': str(self.row.generation)}

    def assert_actor(self, request, user=None):
        user = user or request.user
        if (not self.expected or not user.is_authenticated or not user.is_active
                or str(user.pk) != self.expected['a']):
            raise BoundaryError()
        return user

    def factor_user(self, request):
        if not self.expected:
            raise BoundaryError()
        if self.expected['p'] == 'pending':
            pending = request.session.get(mfa_session.PENDING_KEY)
            if not isinstance(pending, dict):
                raise BoundaryError('mfa_session_expired', 401)
            stamp = pending.get('ts')
            if (str(pending.get('uid')) != self.expected['a'] or not isinstance(stamp, (int, float))
                    or not 0 <= time.time() - stamp <= mfa_session.PENDING_TTL_SECONDS):
                raise BoundaryError('mfa_session_expired', 401)
            user = get_user_model().objects.filter(pk=pending['uid'], is_active=True).first()
            if user is None:
                raise BoundaryError('mfa_session_expired', 401)
            return user
        if self.expected['p'] == 'mfa':
            return self.assert_actor(request)
        raise BoundaryError()

    def prepare_primary(self, request, user):
        if self.kind != 'start' or not user.is_active:
            raise BoundaryError()
        self.primary_target = user.pk  # only called after native credential verification
        self.new_attempt = True
        logout(request)  # retire previous auth/challenges; request binding survives flush

    def check_completion(self, request, user):
        if self.kind == 'start':
            if self.primary_target != user.pk:
                raise BoundaryError()
        elif self.kind == 'enroll':
            # Enrollment is an authenticated account operation, including optional
            # setup/re-enrollment from a verified session, not pending sign-in.
            if (not self.expected or self.expected['p'] not in {'enrollment', 'verified', 'mfa'}
                    or context.snapshot(request) != self.expected):
                raise BoundaryError()
            if self.assert_actor(request).pk != user.pk:
                raise BoundaryError()
        elif self.kind == 'complete':
            if self.factor_user(request).pk != user.pk:
                raise BoundaryError()
        else:
            raise BoundaryError()

    def restart(self, request):
        if not self.recovery_request:
            raise BoundaryError()
        Session.objects.using(DB).filter(session_key=self.before_key).delete()
        logout(request)
        self.new_attempt = True

    def prepare(self, request):
        if self.prepared:
            return
        if not self.writing or not connection.in_atomic_block:
            raise RuntimeError('Session preparation must be inside the lineage transaction.')
        # Every new attempt gets a new key, including same-account sign-in.
        if self.new_attempt and request.session.session_key == self.before_key:
            request.session.cycle_key()
        mirror = {'l': str(self.row.pk), 'g': str(self.generation)}
        if request.session.get(context.KEY) != mirror:
            request.session[context.KEY] = mirror
        if request.session.modified:
            expiry = min(request.session.get_expiry_date(), self.row.expires_at)
            request.session.set_expiry(expiry)
        self.prepared = True

    def finalize(self, request):
        if not self.saved or not connection.in_atomic_block or connection.alias != DB:
            raise RuntimeError('Both session save and lineage update must share the owning transaction.')
        if self.row.expires_at <= timezone.now():
            raise BoundaryError('gateway_lineage_expired')
        key = request.session.session_key
        stored = Session.objects.using(DB).get(session_key=key).get_decoded()
        if stored.get(context.KEY) != {'l': str(self.row.pk), 'g': str(self.generation)}:
            raise RuntimeError('Persisted session does not match lineage generation.')
        old = self.before_key
        changed = self.row.generation != self.generation or self.row.session_key != key
        self.row.generation = self.generation
        self.new_attempt = False
        if changed:
            self.row.session_key = key
            self.row.save(using=DB, update_fields=['generation', 'session_key'])
        if old and old != key:
            Session.objects.using(DB).filter(session_key=old).delete()


def auth_login(sender, request, user, **kwargs):
    state = getattr(request, 'gateway_lineage', None) if request is not None else None
    if not settings.JTH_GATEWAY or state is None:
        return
    if state.kind != 'complete':
        state.new_attempt = True
        state.primary_target = user.pk
        # Standard Django/admin new sign-ins must not inherit MFA/challenges.
        for key in (mfa_session.PENDING_KEY, mfa_session.VERIFIED_KEY, 'webauthn_challenge'):
            request.session.pop(key, None)


def auth_logout(sender, request, **kwargs):
    state = getattr(request, 'gateway_lineage', None) if request is not None else None
    if settings.JTH_GATEWAY and state is not None:
        state.new_attempt = True
