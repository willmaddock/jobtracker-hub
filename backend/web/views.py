"""Server-rendered product pages. Every page requires login and scopes by owner (404 otherwise)."""
from collections import Counter

from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import Workspace
from applications.derivation import effective_status
from applications.models import Application

STATUSES = ["drafted", "applied", "interviewing", "ghosted", "rejected", "unknown"]

NAV = [
    ("pipeline", "Pipeline"),
    ("attention", "Needs Attention"),
    ("browse", "Browse by Section"),
    ("search-hub", "Search Hub"),
    ("email-sync", "Email Sync"),
    ("insights", "Insights"),
    ("manage", "Manage"),
]


def _shell(request, workspace, active):
    return {
        "workspace": workspace,
        "workspaces": request.user.workspaces.all(),
        "nav": [{"key": k, "label": l, "ready": k == "pipeline", "active": k == active} for k, l in NAV],
    }


@login_required
def home(request):
    workspace = request.user.workspaces.first()
    if workspace is None:
        return render(request, "web/no_workspace.html")
    return redirect("web:pipeline", workspace_id=workspace.pk)


@login_required
@require_POST
def sign_out(request):
    logout(request)
    return redirect("/")


@login_required
def pipeline(request, workspace_id):
    workspace = get_object_or_404(Workspace, pk=workspace_id, owner=request.user)
    apps = list(
        Application.objects.live()
        .filter(workspace=workspace, section="applications")
        .select_related("override")
        .order_by("company", "role_label")
    )
    # A manual status (Override) takes precedence over the automatic one, the same
    # rule the API uses for `effective_status`.
    labels = dict(Application.STATUS_CHOICES)
    for app in apps:
        app.shown_status = effective_status(app)
        app.shown_status_label = labels.get(app.shown_status, app.shown_status)
    counts = Counter(app.shown_status for app in apps)
    context = _shell(request, workspace, "pipeline")
    context.update(
        applications=apps,
        total=len(apps),
        stats=[{"status": s, "count": counts.get(s, 0)} for s in STATUSES],
    )
    return render(request, "web/pipeline.html", context)
