from django.apps import AppConfig


class EmailSyncConfig(AppConfig):
    name = 'email_sync'

    def ready(self):
        # Importing email_sync.oauth registers "gmail" against
        # providers.get_provider() (see oauth.py's @register_provider
        # usage) as a side effect of module import. Doing that here,
        # in AppConfig.ready(), rather than relying on some view or
        # urls.py happening to import oauth.py first, means
        # get_provider("gmail") resolves correctly regardless of
        # import order or which entrypoint (runserver, a management
        # command, a Celery worker) started the app.
        from . import oauth  # noqa: F401
