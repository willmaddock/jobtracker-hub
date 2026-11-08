import http.client
import json

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from gateway.backends import Backends, BackendError


class Command(BaseCommand):
    help = "Link an existing JobTracker folder on THIS computer, in place (nothing is copied), to a user's private app."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="Email of the signed-up user")
        parser.add_argument("--path", required=True, help="Folder that contains your Applications/ folder")
        parser.add_argument("--name", default="Job Search", help="Tracker name shown in the app")

    def handle(self, *args, **opts):
        user = get_user_model().objects.filter(email__iexact=opts["email"]).first()
        if user is None:
            raise CommandError("No user with that email. Sign in once in the browser first.")
        try:
            be = Backends(settings.JTH_DATA_DIR, settings.JTH_APP_SOURCE, settings.JTH_IDLE_MINUTES).ensure(user)
        except BackendError as exc:
            raise CommandError(str(exc))
        body = json.dumps({"name": opts["name"], "path": opts["path"]}).encode()
        conn = http.client.HTTPConnection("127.0.0.1", be.port, timeout=1800)
        conn.request("POST", "/api/workspaces/link", body=body, headers={
            "Content-Type": "application/json", "X-JTH-Gateway-Token": be.token, "X-JTH-Allow-Local": "1"})
        resp = conn.getresponse()
        data = resp.read().decode("utf-8", "replace")
        conn.close()
        if resp.status != 200:
            raise CommandError(f"Link failed ({resp.status}): {data}")
        self.stdout.write(self.style.SUCCESS("Linked. Refresh the browser tab. " + data))
