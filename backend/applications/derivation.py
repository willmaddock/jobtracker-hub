"""Explicit per-Application authority; callers never derive on reads or signals.

The public entry point owns the workspace gate, then Application and Document
locks. Mutation callers already holding that gate share the same transaction.
No storage writes, historical backfill, or cross-Application cache refresh occurs.
"""
import hashlib
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound

from applications.creation import lock_workspace
from applications.models import Application, Override, StatusHistory
from documents.extraction import EXTRACTOR_VERSION, get_or_extract
from documents.models import Document, DocumentExtraction
from documents.services import effective_doc_type

VERSION = "1"
PRIORITY = (("rejection_notice", "rejected"), ("interview_notice", "interviewing"),
            ("application_confirmation", "applied"), ("resume", "drafted"), ("cover_letter", "drafted"))
EVENT_TYPES = {"application_confirmation", "interview_notice", "rejection_notice"}


def effective_status(application):
    override = getattr(application, "override", None)
    return (override.manual_status if override else None) or application.status


def effective_date(application):
    override = getattr(application, "override", None)
    if override:
        if override.date_applied_mode == "suppressed":
            return None
        if override.date_applied_mode in {"manual", "legacy_preserved"}:
            return override.date_applied
        # Protect unreconciled direct/legacy writers too; migration labels these.
        if override.date_applied:
            return override.date_applied
    return application.automatic_date_applied


def record_transition(application, previous, source):
    current = effective_status(application)
    if current == previous:
        return
    latest = application.status_history.order_by("-id").first()
    if latest is None or latest.status != current:
        StatusHistory.objects.create(application=application, status=current,
                                     changed_at=timezone.now(), source=source)


def calendar_day(value, zone):
    if isinstance(value, datetime):
        return value.astimezone(zone).date() if timezone.is_aware(value) else None
    return value if isinstance(value, date) else None


def validate_cache_scope(workspace, documents):
    caches = DocumentExtraction.objects.filter(workspace=workspace,
        content_hash__in=[d.content_hash for d in documents], document__isnull=False)
    if caches.exclude(document__workspace=workspace).exists() or caches.exclude(
            document__application__workspace=workspace).exists():
        raise NotFound()


def _source(document, kind, extraction):
    """Select a fact; extraction version/date candidates remain byte-derived."""
    if document.evidence_event_at or document.evidence_event_date:
        value = document.evidence_event_at or document.evidence_event_date
        if isinstance(value, datetime) and timezone.is_naive(value):
            return None, "uncertain_source_time"
        return value, "evidence_event"
    # Only identified event documents turn the conservative text pattern into
    # activity. A date on a posting/resume is never a submission event.
    if kind in EVENT_TYPES:
        evidence = extraction.get("date_evidence", {})
        if evidence.get("state") == "conflicted":
            return None, "conflicted_event"
        if evidence.get("date"):
            return date.fromisoformat(evidence["date"]), "extracted_event"
    if document.verified_legacy_mtime:
        return document.verified_legacy_mtime, "verified_legacy_mtime"
    if document.original_upload_at:
        return document.original_upload_at, "original_user_upload"
    return None, "unknown"


def _bound(facts, zone, last=False):
    known = [(value, doc_id, source) for value, doc_id, source in facts if calendar_day(value, zone)]
    if not known:
        return None, None, {"precision": "unknown", "documents": []}
    day = (max if last else min)(calendar_day(v, zone) for v, _, _ in known)
    same_day = [(v, pk, src) for v, pk, src in known if calendar_day(v, zone) == day]
    # A date on the boundary makes within-day ordering unknowable.
    date_only = any(not isinstance(v, datetime) for v, _, _ in same_day)
    value = day if date_only else (max if last else min)(v for v, _, _ in same_day)
    support = [{"document_id": pk, "source": src} for v, pk, src in same_day if date_only or v == value]
    return (None, value, {"precision": "date", "documents": support}) if date_only else (
        value, None, {"precision": "instant", "documents": support})


def _derive_locked(application, *, previous=None, source="automatic", record_history=True):
    if application.is_trashed:
        # Parent lifecycle retains its last valid business snapshot.
        return application
    workspace = application.workspace
    previous = effective_status(application) if previous is None else previous
    documents = list(Document.objects.live().filter(workspace=workspace, application=application)
                     .order_by("pk").select_for_update())
    validate_cache_scope(workspace, documents)
    facts, inputs, confirmations = [], [], []
    incomplete = False
    conflicted = False
    for document in documents:
        kind = effective_doc_type(document)
        extraction = get_or_extract(document)
        value, selected = _source(document, kind, extraction)
        facts.append((value, document.pk, selected))
        evidence = extraction.get("date_evidence", {})
        if kind == "application_confirmation":
            # Explicit document-owned event facts take precedence over text.
            strong_date = calendar_day(document.evidence_event_at or document.evidence_event_date,
                                       ZoneInfo(workspace.calendar_timezone))
            if strong_date:
                confirmations.append({"document_id": document.pk, "date": strong_date.isoformat(), "source": "evidence_event"})
            else:
                for candidate in evidence.get("candidates", []):
                    confirmations.append({"document_id": document.pk, **candidate})
                conflicted |= evidence.get("state") == "conflicted"
        incomplete |= value is None or not extraction.get("extraction_ok", False)
        inputs.append({"document_id": document.pk, "hash": document.content_hash, "type": kind,
            "event_at": document.evidence_event_at, "event_date": document.evidence_event_date,
            "event_provenance": document.evidence_event_provenance,
            "legacy_mtime": document.verified_legacy_mtime, "original_upload": document.original_upload_at,
            "selected": selected, "value": value, "extraction_ok": extraction.get("extraction_ok"),
            "date_evidence": evidence, "extractor_version": EXTRACTOR_VERSION})
    types = {row["type"] for row in inputs}
    status = next((status for kind, status in PRIORITY if kind in types), "unknown") if application.section == "applications" else "n/a"
    zone = ZoneInfo(workspace.calendar_timezone)
    first_at, first_date, first_prov = _bound(facts, zone)
    last_at, last_date, last_prov = _bound(facts, zone, last=True)
    dates = {c["date"] for c in confirmations}
    conflicted |= len(dates) > 1
    candidate = date.fromisoformat(next(iter(dates))) if len(dates) == 1 and not conflicted else None
    date_state = "conflicted" if conflicted else "current" if candidate else "unavailable"
    override = getattr(application, "override", None)
    fingerprint = hashlib.sha256(json.dumps({"version": VERSION, "section": application.section,
        "timezone": workspace.calendar_timezone, "evidence": inputs,
        "manual_status": override.manual_status if override else None,
        "date_mode": override.date_applied_mode if override else "automatic",
        "stored_date": override.date_applied if override else None}, sort_keys=True, default=str).encode()).hexdigest()
    updates = dict(status=status, first_activity=first_at, first_activity_date=first_date,
        last_activity=last_at, last_activity_date=last_date,
        activity_provenance={"first": first_prov, "last": last_prov, "timezone": workspace.calendar_timezone},
        automatic_date_applied=candidate,
        date_candidate={"state": date_state, "support": confirmations, "extractor_version": EXTRACTOR_VERSION},
        derivation_version=VERSION, derivation_fingerprint=fingerprint,
        derivation_state="incomplete" if incomplete or conflicted else "current")
    changed = [key for key, value in updates.items() if getattr(application, key) != value]
    if changed:
        for key in changed:
            setattr(application, key, updates[key])
        application.derived_at = timezone.now()
        application.save(update_fields=changed + ["derived_at"])
    if record_history:
        record_transition(application, previous, source)
    return application


def derive_application(*, actor, workspace, application_id, record_history=True):
    """Single explicit per-Application operation; repair callers can suppress history.

    Extraction completion is synchronous here. Never refresh a shared cache by
    force: identical bytes may belong to another Application whose snapshot must
    not change outside its own explicit operation.
    """
    with transaction.atomic():
        lock_workspace(actor, workspace)
        application = Application.objects.select_for_update().filter(pk=application_id, workspace=workspace).first()
        if application is None:
            raise NotFound()
        application.workspace = workspace
        return _derive_locked(application, record_history=record_history)


def apply_overrides(*, actor, workspace, application_id, fields):
    with transaction.atomic():
        lock_workspace(actor, workspace)
        application = Application.objects.select_for_update().get(pk=application_id, workspace=workspace)
        from core.lifecycle import require_live
        require_live(application)
        previous = effective_status(application)
        if fields:
            Override.objects.update_or_create(application=application, defaults=fields)
            application._state.fields_cache.pop("override", None)
        if "manual_status" in fields or "date_applied_mode" in fields:
            return _derive_locked(application, previous=previous, source="manual")
        return application
