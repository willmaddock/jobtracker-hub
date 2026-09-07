"""
core services.

Phase 8 (docs/DJANGO_MIGRATION_PLAN.md) port of the "cross-cutting
views" group from _app/db.py (load_applications' enrichment,
compute_metrics, needs_attention, suggest_duplicate_companies,
find_duplicate_groups) and _app/classify.py's normalize_company_key.

These functions operated on sqlite3.Row dicts pulled from two
separate local databases (jobtracker.db for the disposable index,
overrides.db for durable user data). There's one Django database now
and Application/Override/CompanyAlias/Document are real rows with
real FKs, so the shape here is: pull a queryset, enrich each instance
into the same dict shape load_applications() used to return, then run
the same pure functions (compute_metrics, needs_attention,
suggest_duplicate_companies) unchanged over that list of dicts. The
enrichment itself (annotate_application) is the one function that
actually had to be rewritten -- it used to read two dict lookups
(overrides.get(item_key), aliases.get(company)) and now reads an
Application instance's .override relation plus a per-workspace
CompanyAlias lookup instead.

Every entry point here takes an already-ownership-filtered queryset
(``Application.objects.filter(workspace__owner=request.user)``,
same as ApplicationViewSet.get_queryset) rather than a workspace_id --
Attention/Insights/Search/Browse/Manage all aggregate across every
workspace a user owns, matching how documents/views.py's
CategoryListView already aggregates categories across workspaces
(a user can own more than one Workspace -- see accounts/models.py).
Hub settings is the one exception: HubSettings is a real
OneToOneField(Workspace) singleton, so that view (core/views.py)
takes an explicit workspace id, the same way
CategoryOverrideView/CategoryDeleteView already require one in the
request body.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone as dt_timezone

from django.db.models import Count
from django.utils import timezone as dj_timezone

from applications.models import Application, CompanyAlias
from documents.models import Document

STATUS_ORDER = ["drafted", "applied", "interviewing", "rejected", "unknown"]

# applied/interviewing with no update in this long -> needs attention
STALE_APPLIED_DAYS = 21
# drafted/unknown untouched this long -> needs attention
STALE_DRAFTED_DAYS = 14


def _as_aware_datetime(value) -> datetime | None:
    """Application.last_activity/first_activity are DateTimeFields;
    Override.date_applied/next_action_date/snoozed_until/
    activity_override are plain DateFields. Both flow through the
    same staleness/due/snooze math below, so normalize either shape
    to an aware datetime (midnight UTC for a bare date) once here
    instead of duplicating the isinstance check at each call site.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt_timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=dt_timezone.utc)
    return None


def _days_since(value) -> int | None:
    dt = _as_aware_datetime(value)
    if dt is None:
        return None
    return (dj_timezone.now() - dt).days


def annotate_application(application: Application) -> dict:
    """Enriches one Application instance into the same dict shape
    _app/db.py's load_applications() used to build per row. Expects
    `application.override` to already be select_related (a missing
    Override is fine -- getattr(..., None) below, same as the old
    overrides.get(item_key, {}) default).
    """
    override = getattr(application, "override", None)
    manual_status = override.manual_status if override else None
    notes = override.notes if override else None
    date_applied = override.date_applied if override else None
    date_applied_source = override.date_applied_source if override else None
    next_action = override.next_action if override else None
    next_action_date = override.next_action_date if override else None
    archived = bool(override.archived) if override else False
    snoozed_until = override.snoozed_until if override else None
    activity_override = override.activity_override if override else None

    effective_status = manual_status or application.status

    # Reference date for "how long has this been sitting" --
    # activity_override wins first (explicit "Reset activity clock",
    # e.g. after an interview or a follow-up, without touching
    # date_applied itself), then date_applied, then the (unreliable)
    # last_activity as a last resort.
    reference = activity_override or date_applied or application.last_activity
    days_since_activity = _days_since(reference)

    is_stale = False
    if not archived and days_since_activity is not None:
        if effective_status in ("applied", "interviewing") and days_since_activity >= STALE_APPLIED_DAYS:
            is_stale = True
        elif effective_status in ("drafted", "unknown") and days_since_activity >= STALE_DRAFTED_DAYS:
            is_stale = True

    now = dj_timezone.now()
    next_due_dt = _as_aware_datetime(next_action_date)
    next_action_due = bool(next_due_dt and next_due_dt <= now)

    snoozed_dt = _as_aware_datetime(snoozed_until)
    is_snoozed = bool(snoozed_dt and snoozed_dt > now)

    return {
        "id": application.id,
        "workspace_id": application.workspace_id,
        "section": application.section,
        "company": application.company,
        "role_label": application.role_label,
        "status": application.status,
        "manual_status": manual_status,
        "effective_status": effective_status,
        "notes": notes,
        "date_applied": date_applied,
        "date_applied_source": date_applied_source,
        "next_action": next_action,
        "next_action_date": next_action_date,
        "archived": archived,
        "snoozed_until": snoozed_until,
        "activity_override": activity_override,
        "last_activity": application.last_activity,
        "days_since_activity": days_since_activity,
        "date_is_manual": bool(date_applied),
        "activity_is_reset": bool(activity_override),
        "is_stale": is_stale,
        "next_action_due": next_action_due,
        "is_snoozed": is_snoozed,
    }


def load_applications(queryset) -> list[dict]:
    """Every Application in `queryset`, enriched -- the multi-instance
    equivalent of annotate_application(), plus the effective_company
    alias lookup that only makes sense once you have more than one
    row (CompanyAlias is workspace-scoped, so this caches one lookup
    per distinct workspace_id in the queryset rather than querying it
    per row).
    """
    applications = list(queryset.select_related("override"))
    aliases_by_workspace: dict[int, dict[str, str]] = {}
    out = []
    for application in applications:
        row = annotate_application(application)
        workspace_id = application.workspace_id
        if workspace_id not in aliases_by_workspace:
            aliases_by_workspace[workspace_id] = dict(
                CompanyAlias.objects.filter(workspace_id=workspace_id).values_list(
                    "alias", "canonical"
                )
            )
        row["effective_company"] = aliases_by_workspace[workspace_id].get(
            row["company"], row["company"]
        )
        out.append(row)
    return out


def compute_metrics(apps: list[dict]) -> dict:
    active = [a for a in apps if not a["archived"]]
    total = len(active)
    by_status = {s: 0 for s in STATUS_ORDER}
    for a in active:
        by_status[a["effective_status"]] = by_status.get(a["effective_status"], 0) + 1

    # "Responded" = got any signal back at all (interview or rejection).
    responded = by_status.get("interviewing", 0) + by_status.get("rejected", 0)
    sent = by_status.get("applied", 0) + by_status.get("interviewing", 0) + by_status.get("rejected", 0)
    response_rate = (responded / sent * 100) if sent else 0.0
    interview_rate = (by_status.get("interviewing", 0) / sent * 100) if sent else 0.0

    # Time-to-response, for items where we have both a date_applied and a
    # last_activity after it (best-effort -- only meaningful when
    # date_applied was set manually, since last_activity is otherwise
    # unreliable).
    lags = []
    for a in active:
        if a["date_applied"] and a["effective_status"] in ("interviewing", "rejected") and a["last_activity"]:
            applied_dt = _as_aware_datetime(a["date_applied"])
            last_dt = _as_aware_datetime(a["last_activity"])
            if applied_dt and last_dt and last_dt > applied_dt:
                lags.append((last_dt - applied_dt).days)
    avg_response_days = round(sum(lags) / len(lags)) if lags else None

    return {
        "total": total,
        "by_status": by_status,
        "response_rate": response_rate,
        "interview_rate": interview_rate,
        "avg_response_days": avg_response_days,
        "lag_sample_size": len(lags),
    }


def needs_attention(apps: list[dict]) -> list[dict]:
    return sorted(
        [
            a for a in apps
            if not a["archived"] and not a["is_snoozed"] and (a["is_stale"] or a["next_action_due"])
        ],
        key=lambda a: (-1 if a["next_action_due"] else 0, -(a["days_since_activity"] or 0)),
    )


def normalize_company_key(name: str) -> str:
    """Loose key for suggesting possible duplicate companies (e.g.
    'Bet365', 'BET 365', 'Bet365 -- ABET' all reduce to 'bet365').
    Only used to power merge *suggestions* in the Manage view -- never
    applied automatically, since a loose match can also be a false
    positive. Ported unchanged from _app/classify.py.
    """
    base = re.split(r"[—-]", name)[0]  # drop " — ABET" / " - via ..." suffixes
    return re.sub(r"[^a-z0-9]", "", base.lower())


def suggest_duplicate_companies(apps: list[dict]) -> dict[str, list[str]]:
    """Group raw company names that normalize to the same loose key.
    Returns {loose_key: [raw_name, raw_name, ...]} for any group with
    2+ distinct raw names.
    """
    groups: dict[str, set[str]] = {}
    for a in apps:
        key = normalize_company_key(a["company"])
        groups.setdefault(key, set()).add(a["company"])
    return {k: sorted(v) for k, v in groups.items() if len(v) > 1}


def find_duplicate_groups(queryset) -> list[dict]:
    """Every content_hash shared by 2+ Documents in `queryset`, with
    each document's owning application (company/role_label) --
    powers the 'Duplicates' list in Manage. Read-only; never used to
    delete or merge files. `queryset` is already ownership-filtered
    the same way every other entry point here expects
    (Document.objects.filter(workspace__owner=request.user)).
    """
    dup_hashes = (
        queryset.exclude(content_hash="")
        .values("content_hash")
        .annotate(count=Count("id"))
        .filter(count__gt=1)
        .values_list("content_hash", flat=True)
    )
    documents = (
        queryset.filter(content_hash__in=list(dup_hashes))
        .select_related("application")
        .order_by("content_hash", "application__company", "application__role_label")
    )
    groups: dict[str, list[dict]] = {}
    for document in documents:
        groups.setdefault(document.content_hash, []).append({
            "id": document.id,
            "filename": document.filename,
            "doc_type": document.doc_type,
            "company": document.application.company,
            "role_label": document.application.role_label,
        })
    return [{"content_hash": h, "documents": docs} for h, docs in groups.items()]
