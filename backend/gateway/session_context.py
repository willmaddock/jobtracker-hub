"""Versioned transport and phase policy. Authority is in session_lineage, not the token."""
import time
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.http import JsonResponse
from django.urls import Resolver404, resolve
from accounts import mfa, mfa_session

KEY = 'gateway_binding_v2'
HEADER = 'X-JTH-Context'
FORM_FIELD = '_jth_context'
FORM_TYPES = {'application/x-www-form-urlencoded', 'multipart/form-data'}
SALT = 'gateway-context-v2'
COOKIE_SALT = 'gateway-lineage-cookie-v1'
RECOVERY_SALT = 'gateway-lineage-restart-v2'
PUBLIC = {('GET', '/api/health'), ('HEAD', '/api/health'),
          ('GET', '/api/auth/options'), ('GET', '/api/auth/csrf')}
START = {'auth-login', 'auth-email-verify'}
SECOND = {'auth-mfa-verify', 'auth-mfa-passkey-options', 'auth-mfa-passkey-verify',
          'auth-mfa-email-send', 'auth-mfa-email-verify'}
COMPLETE = {'auth-mfa-verify', 'auth-mfa-passkey-verify', 'auth-mfa-email-verify', 'auth-mfa-enroll-confirm'}
ENROLL = {'auth-mfa-enroll-begin', 'auth-mfa-enroll-confirm', 'auth-mfa-status'}
FLOW = START | SECOND | ENROLL | {'auth-email-start', 'auth-logout', 'auth-me', 'gateway-context'}


def cookie_name():
    return '__Host-jth-gateway-lineage' if settings.SESSION_COOKIE_SECURE else 'jth_gateway_lineage_dev'


def phase(request):
    pending = request.session.get(mfa_session.PENDING_KEY)
    if isinstance(pending, dict):
        uid, stamp = pending.get('uid'), pending.get('ts')
        if (isinstance(uid, int) and isinstance(stamp, (int, float))
                and 0 <= time.time() - stamp <= mfa_session.PENDING_TTL_SECONDS
                and get_user_model().objects.filter(pk=uid, is_active=True).exists()):
            return 'pending', uid
        return 'expired', None  # never fall back to a previous cookie principal
    if request.user.is_authenticated:
        if not settings.MFA_REQUIRED or mfa_session.is_verified(request):
            return 'verified', request.user.pk
        return ('mfa' if mfa.is_enrolled(request.user) else 'enrollment'), request.user.pk
    return 'anonymous', None


def snapshot(request):
    state = getattr(request, 'gateway_lineage', None)
    if state is None:
        return None
    p, a = phase(request)
    return {'v': 2, 'l': str(state.row.pk), 'g': str(state.generation),
            'p': p, 'a': None if a is None else str(a)}


def issue(request):
    value = snapshot(request)
    return {'binding': signing.dumps(value, salt=SALT), 'phase': value['p'], 'actor': value['a']}


def form_route(request):
    """Only real Django form endpoints may use the POST transport, never /api/."""
    if request.path_info.startswith('/api/'):
        return False
    try:
        match = resolve(request.path_info, getattr(request, 'urlconf', None))
    except Resolver404:
        return False
    return ((request.path_info.startswith('/admin/') and match.namespaces == ['admin'])
            or (request.path_info.startswith('/app/') and match.namespaces == ['web']
                and match.url_name in {'sign-out', 'application-action'}))


def form_post(request):
    return request.method == 'POST' and request.content_type in FORM_TYPES and form_route(request)


def validate(request, *, allow_form=False):
    if '_jth_page' in request.GET or '_jth_context' in request.GET:
        return None
    token = request.headers.get(HEADER, '')
    if allow_form and form_post(request):
        fields = request.POST.getlist(FORM_FIELD)
        if len(fields) > 1 or (fields and token and fields[0] != token):
            return None
        if fields:
            token = fields[0]
    if not token or len(token) > 1024:
        return None
    try:
        value = signing.loads(token, salt=SALT, max_age=86400)
    except signing.BadSignature:
        return None
    return value if value == snapshot(request) else None


def permitted(name, p):
    if name in SECOND:
        return p in {'pending', 'mfa'}
    if name in ENROLL:
        return p in {'enrollment', 'verified', 'mfa'}
    return name in FLOW or p == 'verified'


def conflict(code='gateway_context_changed', status=409):
    response = JsonResponse({'code': code, 'detail': 'Sign-in state changed. Reload or restart sign-in.'}, status=status)
    response['Cache-Control'] = 'private, no-store'
    response.gateway_context_rejected = True
    return response


def response_headers(request, response):
    value = snapshot(request)
    if value and value['p'] != 'expired':
        incoming = validate(request)
        response[HEADER] = request.headers[HEADER] if incoming else signing.dumps(value, salt=SALT)
        response['X-JTH-Phase'] = value['p']
        response['X-JTH-Actor'] = '' if value['a'] is None else value['a']
    response['Cache-Control'] = 'private, no-store'
    return response
