"""Server-rendered product pages. Every page requires login and scopes by owner (404 otherwise)."""
from collections import Counter
from datetime import timedelta

from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from rest_framework.exceptions import NotFound

from accounts.models import Workspace
from applications.derivation import apply_overrides
from applications.models import Application
from core.services import load_applications, needs_attention

STATUSES = ["drafted", "applied", "interviewing", "ghosted", "rejected", "unknown"]
STATUS_COLORS = {"drafted": "#94A3B8", "applied": "#6D8BF7", "interviewing": "#34D399",
                 "ghosted": "#A78BFA", "rejected": "#F87171", "unknown": "#64748B"}
SORTS = [("recent", "Recently applied"), ("company", "Company A to Z"), ("quiet", "Longest quiet")]

# (key, label, icon path, ready)
NAV = [
    ("pipeline", "Pipeline", "M4 20V10M10 20V4M16 20v-7M22 20H2", True),
    ("attention", "Needs Attention", "M12 3l10 18H2zM12 10v5M12 18h.01", False),
    ("browse", "Browse by Section", "M3 6a2 2 0 012-2h4l2 3h8a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2z", False),
    ("search-hub", "Search Hub", "M12 8v4M12 12l-6 5M12 12l6 5M12 4m-2 0a2 2 0 104 0 2 2 0 10-4 0M5 19m-2 0a2 2 0 104 0 2 2 0 10-4 0M19 19m-2 0a2 2 0 104 0 2 2 0 10-4 0", False),
    ("email-sync", "Email Sync", "M3 5h18v14H3zM3 7l9 6 9-6", False),
    ("insights", "Insights", "M5 20v-6M12 20V6M19 20v-9", False),
    ("manage", "Manage", "M4 20l4-1 11-11-3-3L5 16zM14 6l3 3", False),
]


def _owned_workspace(request, workspace_id):
    return get_object_or_404(Workspace, pk=workspace_id, owner=request.user)


def _shell(request, workspace, active, attention_count=0):
    return {
        "workspace": workspace,
        "workspaces": request.user.workspaces.all(),
        "nav": [{"key": k, "label": l, "icon": i, "ready": r, "active": k == active,
                 "badge": attention_count if k == "attention" and attention_count else None}
                for k, l, i, r in NAV],
        "year": timezone.now().year,
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


def _days_label(days):
    return "" if days is None else f"{days}d since date applied"


def _sort(rows, key):
    if key == "company":
        return sorted(rows, key=lambda r: (r["effective_company"].lower(), r["role_label"].lower()))
    if key == "quiet":
        return sorted(rows, key=lambda r: -(r["days_since_activity"] if r["days_since_activity"] is not None else -1))
    # Most recently applied first; rows without a date go last.
    dated = [r for r in rows if r["date_applied"]]
    undated = [r for r in rows if not r["date_applied"]]
    dated.sort(key=lambda r: (r["date_applied"], r["id"]), reverse=True)
    undated.sort(key=lambda r: r["effective_company"].lower())
    return dated + undated


@login_required
def pipeline(request, workspace_id):
    workspace = _owned_workspace(request, workspace_id)
    queryset = Application.objects.live().filter(workspace=workspace, section="applications")
    everything = load_applications(queryset)
    attention_count = len(needs_attention(everything))

    q = request.GET.get("q", "").strip()
    view = "kanban" if request.GET.get("view") == "kanban" else "list"
    sort = request.GET.get("sort") if request.GET.get("sort") in dict(SORTS) else "recent"
    show_archived = request.GET.get("archived") == "1"
    status_filter = [s for s in request.GET.getlist("status") if s in STATUSES]

    rows = [r for r in everything if show_archived or not r["archived"]]
    if q:
        needle = q.lower()
        rows = [r for r in rows if needle in r["effective_company"].lower() or needle in r["role_label"].lower()]
    counts = Counter(r["effective_status"] for r in rows)
    shown = [r for r in rows if not status_filter or r["effective_status"] in status_filter]
    shown = _sort(shown, sort)

    selected = None
    if view == "list" and shown:
        try:
            wanted = int(request.GET.get("selected", ""))
        except ValueError:
            wanted = None
        selected = next((r for r in shown if r["id"] == wanted), shown[0])
        history = list(Application.objects.get(pk=selected["id"]).status_history.order_by("-changed_at", "-id")[:8])
        selected = dict(selected, history=history)

    columns = [{"status": s, "color": STATUS_COLORS[s], "cards": [r for r in shown if r["effective_status"] == s]}
               for s in STATUSES]

    def link(**changes):
        params = {"view": view, "sort": sort}
        if q:
            params["q"] = q
        if show_archived:
            params["archived"] = "1"
        params.update(changes)
        if params.get("status") is None:
            params.pop("status", None)
        qs = []
        for k, v in params.items():
            if v in (None, ""):
                continue
            for item in (v if isinstance(v, list) else [v]):
                qs.append(f"{k}={item}")
        return "?" + "&".join(qs)

    for r in shown:
        r["href"] = link(selected=r["id"], view="list")
    chips = []
    for s in STATUSES:
        nxt = [x for x in status_filter if x != s] if s in status_filter else status_filter + [s]
        chips.append({"status": s, "on": s in status_filter, "href": link(status=nxt or None)})

    context = _shell(request, workspace, "pipeline", attention_count)
    context.update(
        rows=shown, selected=selected, columns=columns, view=view, sort=sort, sorts=SORTS, q=q,
        show_archived=show_archived, total=len(rows), shown_count=len(shown),
        stats=[{"status": s, "count": counts.get(s, 0)} for s in STATUSES],
        statuses=STATUSES, status_filter=status_filter, chips=chips, list_href=link(view="list"), kanban_href=link(view="kanban"),
        back=request.get_full_path(),
    )
    return render(request, "web/pipeline.html", context)


def _safe_back(request, workspace):
    back = request.POST.get("next", "")
    own = reverse("web:pipeline", args=[workspace.pk])
    return back if back.startswith(own) and "//" not in back else own


def _today(workspace):
    from zoneinfo import ZoneInfo
    return timezone.now().astimezone(ZoneInfo(workspace.calendar_timezone)).date()


@login_required
@require_POST
def application_action(request, workspace_id, application_id, action):
    """Small status actions from the Pipeline: set status, follow up, reset the activity clock."""
    workspace = _owned_workspace(request, workspace_id)
    application = get_object_or_404(Application, pk=application_id, workspace=workspace)
    today = _today(workspace)
    if action == "status":
        value = request.POST.get("status", "")
        if value == "":
            fields = {"manual_status": None}  # back to the automatic status
        elif value in STATUSES:
            fields = {"manual_status": value}
        else:
            raise Http404
    elif action == "follow-up":
        fields = {"next_action": "Follow up", "next_action_date": today + timedelta(days=7)}
    elif action == "reset-clock":
        fields = {"activity_override": today}
    else:
        raise Http404
    try:
        apply_overrides(actor=request.user, workspace=workspace, application_id=application.pk, fields=fields)
    except NotFound:
        raise Http404
    return redirect(_safe_back(request, workspace))
