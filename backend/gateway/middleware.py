"""Gateway lineage boundary, enclosing Django's real session response save.

Native operations hold the stable lineage lock through session persistence. Proxy
I/O uses a short authorization transaction and an immutable principal snapshot.
Ordinary Django deployments delegate to the unmodified session middleware.
"""
from django.conf import settings
from django.contrib.sessions.middleware import SessionMiddleware
from django.db import DatabaseError, transaction
from django.core.exceptions import RequestDataTooBig, TooManyFieldsSent, TooManyFilesSent
from django.http.multipartparser import MultiPartParserError
from django.http import HttpResponse, JsonResponse
from django.urls import Resolver404, resolve
from django.utils import timezone
from . import session_context as context, session_lineage as lineage


def native(request):
    path = request.path_info
    return (path in {'/', '/app', '/admin', '/api/workspaces/'}
            or path.startswith(('/api/auth/', '/api/account/', '/api/gateway/', '/app/', '/admin/')))


class AbortResponse(Exception):
    def __init__(self, response):
        self.response = response


def clean(response):
    response.cookies.pop(settings.SESSION_COOKIE_NAME, None)
    response.cookies.pop(context.cookie_name(), None)
    return response


class GatewaySessionLockMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        if settings.JTH_GATEWAY:
            lineage.check_configuration()
            order = settings.MIDDLEWARE
            required = [__name__ + '.GatewaySessionLockMiddleware', __name__ + '.GatewaySessionMiddleware',
                        'django.middleware.csrf.CsrfViewMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware', __name__ + '.GatewayContextMiddleware']
            if [order.index(x) for x in required] != sorted(order.index(x) for x in required):
                from django.core.exceptions import ImproperlyConfigured
                raise ImproperlyConfigured('Gateway session middleware ordering is invalid.')

    @staticmethod
    def form_failure(request, code, status=409):
        if context.form_post(request):
            from .views import form_conflict
            return form_conflict(code, status)
        return context.conflict(code, status)

    def __call__(self, request):
        if not settings.JTH_GATEWAY:
            return self.get_response(request)
        if any(name in request.GET for name in ('_jth_context', '_jth_page')):
            return context.conflict('gateway_context_in_url')
        public = (request.method, request.path_info) in context.PUBLIC
        if public or not native(request):
            response = self.get_response(request)
            return clean(response) if getattr(response, 'gateway_context_rejected', False) else response
        try:
            if context.form_post(request):
                sensitive = getattr(request, 'sensitive_post_parameters', ())
                if sensitive != '__ALL__':
                    request.sensitive_post_parameters = (*sensitive, context.FORM_FIELD)
                # This is a rejection-only hint, never authorization. Do not load
                # a Django session or hold an authority lock while reading uploads.
                from .models import GatewaySessionLineage
                pk = lineage.cookie_id(request)
                hint = GatewaySessionLineage.objects.filter(pk=pk).first() if pk else None
                if hint is None or hint.expires_at <= timezone.now():
                    return clean(self.form_failure(request, 'gateway_lineage_expired'))
                if request.COOKIES.get(settings.SESSION_COOKIE_NAME) != hint.session_key:
                    return clean(self.form_failure(request, 'gateway_session_obsolete'))
                try:
                    length = int(request.META.get('CONTENT_LENGTH') or 0)
                    if length < 0:
                        raise ValueError()
                    if length > settings.JTH_MAX_UPLOAD_MB * 1024 * 1024:
                        return self.form_failure(request, 'gateway_form_too_large', 413)
                    request.POST  # Django parser preserves FILES and upload handlers.
                except (ValueError, RequestDataTooBig, TooManyFieldsSent, TooManyFilesSent, MultiPartParserError):
                    return self.form_failure(request, 'gateway_form_invalid', 400)
            with transaction.atomic(using=lineage.DB):
                pk = lineage.cookie_id(request)
                row = lineage.lock(pk) if pk else None
                bootstrap = request.method == 'GET' and request.path_info in {'/', '/admin/login/'}
                if row is None or row.expires_at <= timezone.now():
                    if not bootstrap:
                        if request.method == 'GET' and (request.path_info in {'/app','/admin'} or request.path_info.startswith(('/app/', '/admin/'))):
                            from django.contrib.auth.views import redirect_to_login
                            target = '/admin/login/' if request.path_info == '/admin' or request.path_info.startswith('/admin/') else settings.LOGIN_URL
                            raise AbortResponse(redirect_to_login(request.get_full_path(), target))
                        raise AbortResponse(context.conflict('gateway_lineage_expired'))
                    row = lineage.fresh()
                    initial = True
                else:
                    initial = False
                restart = request.path_info == '/api/gateway/session/restart'
                if not initial and not restart and request.COOKIES.get(settings.SESSION_COOKIE_NAME) != row.session_key:
                    if request.method == 'GET' and (request.path_info == '/' or request.path_info.startswith(('/app/', '/admin/'))):
                        from .views import recovery_page
                        raise AbortResponse(recovery_page(request, row))
                    raise AbortResponse(self.form_failure(request, 'gateway_session_obsolete'))
                state = request.gateway_lineage = lineage.Binding(row, writing=True, bootstrap=initial, recovery_request=restart)
                response = self.get_response(request)
                if state.rejected or getattr(response, 'gateway_context_rejected', False) or response.status_code >= 500:
                    raise AbortResponse(response)
                state.finalize(request)
                context.response_headers(request, response)
                if initial:
                    from django.core import signing
                    response.set_cookie(context.cookie_name(), signing.dumps(str(row.pk), salt=context.COOKIE_SALT),
                                        max_age=settings.SESSION_COOKIE_AGE, secure=settings.SESSION_COOKIE_SECURE,
                                        httponly=True, samesite='Lax', path='/')
            return response
        except AbortResponse as exc:
            return clean(exc.response)
        except lineage.BoundaryError as exc:
            return clean(context.conflict(exc.code, exc.status))
        except DatabaseError:
            return clean(context.conflict('gateway_session_unavailable', 503))


class GatewaySessionMiddleware(SessionMiddleware):
    """Keep the framework save inside the authority transaction; suppress stale writes."""
    def process_request(self, request):
        super().process_request(request)
        state = getattr(request, 'gateway_lineage', None)
        if state and state.bootstrap:
            # Missing lineage cannot adopt an unrelated, previously authenticated cookie.
            request.session = self.SessionStore()

    def process_response(self, request, response):
        if not settings.JTH_GATEWAY:
            return super().process_response(request, response)
        state = getattr(request, 'gateway_lineage', None)
        if state and state.writing:
            if response.status_code >= 500 or state.rejected or getattr(response, 'gateway_context_rejected', False):
                return clean(response)
            state.prepare(request)
            response = super().process_response(request, response)
            state.saved = True
            return response
        # Public bootstrap endpoints and proxy responses cannot save a session
        # snapshot after their authorization transaction has ended.
        if getattr(request, 'session', None) is not None and request.session.modified:
            return context.conflict('gateway_session_changed')
        if state and hasattr(state, 'rotation_cookie'):
            # Rotation was saved under the lock, before proxy dispatch. Only emit
            # its cookie if no subsequent transition has superseded it.
            from .models import GatewaySessionLineage
            if GatewaySessionLineage.objects.filter(pk=state.row.pk, generation=state.row.generation,
                                                   session_key=state.row.session_key).exists():
                response.cookies.update(state.rotation_cookie)
        return response


class GatewayContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def process_exception(self, request, exception):
        if isinstance(exception, lineage.BoundaryError):
            state = getattr(request, 'gateway_lineage', None)
            if state:
                return state.reject(exception.code, exception.status)

    def __call__(self, request):
        if not settings.JTH_GATEWAY:
            return self.get_response(request)
        state = getattr(request, 'gateway_lineage', None)
        if not request.path_info.startswith('/api/'):
            if state and state.writing:
                if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
                    value = context.validate(request, allow_form=True)
                    if value is None or value['p'] == 'expired' or not state.matches_session(request):
                        state.rejected = True
                        return GatewaySessionLockMiddleware.form_failure(request, 'gateway_context_changed')
                    state.expected = request.gateway_context = value
                # Resolve Django authentication (including hash/key rotation) while
                # the owning transaction is active, before issuing a page context.
                bool(request.user.is_authenticated)
                if not state.bootstrap and not state.matches_session(request):
                    from .views import recovery_page
                    return state.reject() if request.path_info != '/' else recovery_page(request, state.row)
                if context.phase(request)[0] == 'expired':
                    from .views import recovery_page
                    return recovery_page(request, state.row)
                if request.path_info == "/":
                    state.prepare(request)
            return self.get_response(request)
        if (request.method, request.path_info) in context.PUBLIC:
            return self.get_response(request)
        if state is None:
            try:
                with transaction.atomic(using=lineage.DB):
                    pk = lineage.cookie_id(request)
                    row = lineage.lock(pk) if pk else None
                    if row is None or row.expires_at <= timezone.now():
                        return context.conflict('gateway_lineage_expired')
                    if request.COOKIES.get(settings.SESSION_COOKIE_NAME) != row.session_key:
                        return context.conflict('gateway_session_obsolete')
                    state = request.gateway_lineage = lineage.Binding(row, writing=False)
                    response = self.authorize(request, state)
                    if response is not None:
                        if not getattr(response, "gateway_context_rejected", False):
                            context.response_headers(request, response)
                        raise AbortResponse(response)
                    # AuthenticationMiddleware can rotate a key using SECRET_KEY_FALLBACKS.
                    if request.session.modified:
                        state.writing = True
                        state.prepare(request)
                        cookie_response = SessionMiddleware.process_response(GatewaySessionMiddleware(lambda r: None), request, HttpResponse())
                        state.saved = True
                        state.finalize(request)
                        state.rotation_cookie = cookie_response.cookies
                        state.writing = False
                        request.session.modified = False
            except AbortResponse as exc:
                return clean(exc.response)
            except DatabaseError:
                return context.conflict('gateway_session_unavailable', 503)
            response = self.get_response(request)
            return context.response_headers(request, response)
        response = self.authorize(request, state)
        return response if response is not None else self.get_response(request)

    def authorize(self, request, state):
        try:
            name = resolve(request.path_info, getattr(request, 'urlconf', None)).url_name
        except Resolver404:
            name = None
        state.kind = ('enroll' if name == 'auth-mfa-enroll-confirm' else
                      'restart' if name == 'gateway-restart' else 'start' if name in context.START else
                      'complete' if name in context.COMPLETE else 'logout' if name == 'auth-logout' else 'other')
        if state.recovery_request:
            from .views import context_restart
            return context_restart(request)
        bool(request.user.is_authenticated)
        if not state.matches_session(request):
            return state.reject('gateway_session_obsolete')
        if context.phase(request)[0] == 'expired':
            return state.reject('mfa_session_expired', 401)
        value = context.validate(request)
        if value is None:
            return state.reject()
        state.expected = request.gateway_context = value
        if name == 'auth-me' and value['p'] == 'pending':
            return JsonResponse({'code':'authentication_required','detail':'Complete sign-in.'}, status=401)
        if not context.permitted(name, value['p']):
            return JsonResponse({'code':'mfa_enrollment_required' if value['p'] == 'enrollment' else 'mfa_required', 'detail':'Complete sign-in.'}, status=403)
        if name == 'gateway-context' and request.method == 'GET':
            return HttpResponse(status=204)
        return None
