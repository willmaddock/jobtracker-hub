from django.apps import AppConfig


class GatewayConfig(AppConfig):
    name = "gateway"

    def ready(self):
        from django.contrib.auth.signals import user_logged_in, user_logged_out
        from .session_lineage import auth_login, auth_logout
        user_logged_in.connect(auth_login, dispatch_uid='gateway-lineage-login')
        user_logged_out.connect(auth_logout, dispatch_uid='gateway-lineage-logout')
