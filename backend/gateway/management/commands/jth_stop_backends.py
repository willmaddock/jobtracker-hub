from django.conf import settings
from django.core.management.base import BaseCommand

from gateway.backends import Backends


class Command(BaseCommand):
    help = "Stop per-user app processes (idle ones by default, all with --all)."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true")

    def handle(self, *args, **opts):
        b = Backends(settings.JTH_DATA_DIR, settings.JTH_APP_SOURCE, settings.JTH_IDLE_MINUTES)
        n = b.stop_all() if opts["all"] else b.stop_idle()
        self.stdout.write(f"stopped {n} process(es)")
