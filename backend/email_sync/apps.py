from django.apps import AppConfig


class EmailSyncConfig(AppConfig):
    name = 'email_sync'

    def ready(self):
        # Importing email_sync.oauth / email_sync.outlook_oauth /
        # email_sync.imap_auth registers "gmail" / "outlook" / "imap"
        # against providers.get_provider() (see each module's own
        # @register_provider usage) as a side effect of module import.
        # Doing that here, in AppConfig.ready(), rather than relying on
        # some view or urls.py happening to import them first, means
        # get_provider("gmail")/get_provider("outlook")/get_provider(
        # "imap") resolve correctly regardless of import order or
        # which entrypoint (runserver, a management command, a Celery
        # worker) started the app.
        from . import imap_auth, oauth, outlook_oauth  # noqa: F401
