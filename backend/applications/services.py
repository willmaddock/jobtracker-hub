"""
applications services.

Phase 5 (docs/DJANGO_MIGRATION_PLAN.md) port of _app/domain/
applications.py -- ported unchanged, not just "largely" unchanged.
It never had a FastAPI or pydantic import: the functions already took
a plain `fields_set: set[str]` and `values: dict` rather than a
request model itself, specifically so they'd need no adapter here.
The only thing that changes at the call site (Phase 8, once the DRF
serializer for save_override/bulk_override exists) is where
fields_set/values come from -- a DRF Serializer's `.validated_data`
plus tracking which keys the client actually sent, in place of
pydantic's `.model_fields_set`/`.model_dump()`. The rules themselves
-- what save_override/bulk_override actually write, and whether that
write should also append a status_history row -- don't change with
the framework underneath them.
"""
from __future__ import annotations


def _resolve_manual_status(fields_set: set, reset_status: bool, manual_status) -> dict:
    """Shared by both functions below. Use fields_set (not `is not
    None`) so an explicitly-sent null (e.g. "Mark followed up"
    clearing next_action/next_action_date) is actually applied
    instead of being indistinguishable from "field not sent at all"
    and silently dropped. reset_status always wins over a
    manual_status sent in the same request.
    """
    if reset_status:
        return {"manual_status": None}
    if "manual_status" in fields_set:
        return {"manual_status": manual_status}
    return {}


def compute_override_fields(fields_set: set, values: dict, reset_status: bool) -> dict:
    """save_override's full field-diffing rule for a single
    Application/Override pair.

    fields_set: which fields the caller actually sent, vs. left
        unset.
    values: the raw values for those fields.
    reset_status: explicit "clear manual_status" flag, distinct from
        just not sending manual_status at all.
    """
    fields: dict = dict(_resolve_manual_status(fields_set, reset_status, values.get("manual_status")))
    if "notes" in fields_set:
        fields["notes"] = values.get("notes")
    if "date_applied" in fields_set:
        fields["date_applied"] = values.get("date_applied")
        # A date_applied write that doesn't also carry a source is a manual
        # retype (or a clear) -- any provenance label from an earlier
        # detected-date accept is now stale, so drop it here rather than
        # leaving a "Detected from ..." caption pointing at a date the user
        # just overwrote by hand. When the caller DOES send a source
        # (accepting a suggestion), the branch below applies it instead of
        # this default.
        fields["date_applied_source"] = None
    if "date_applied_source" in fields_set:
        fields["date_applied_source"] = values.get("date_applied_source")
    if "next_action" in fields_set:
        fields["next_action"] = values.get("next_action")
    if "next_action_date" in fields_set:
        fields["next_action_date"] = values.get("next_action_date")
    if "archived" in fields_set:
        v = values.get("archived")
        fields["archived"] = bool(v) if v is not None else False
    if "snoozed_until" in fields_set:
        fields["snoozed_until"] = values.get("snoozed_until")
    if "activity_override" in fields_set:
        fields["activity_override"] = values.get("activity_override")
    return fields


def compute_bulk_override_fields(fields_set: set, values: dict, reset_status: bool) -> dict:
    """bulk_override's field-diffing rule -- deliberately a different,
    smaller field set than compute_override_fields above (no notes,
    date_applied, or date_applied_source: bulk actions are
    status/archive/snooze/next-action only, never a per-item notes or
    date edit).
    """
    fields: dict = dict(_resolve_manual_status(fields_set, reset_status, values.get("manual_status")))
    if "archived" in fields_set:
        v = values.get("archived")
        fields["archived"] = bool(v) if v is not None else False
    if "snoozed_until" in fields_set:
        fields["snoozed_until"] = values.get("snoozed_until")
    if "next_action" in fields_set:
        fields["next_action"] = values.get("next_action")
    if "next_action_date" in fields_set:
        fields["next_action_date"] = values.get("next_action_date")
    if "activity_override" in fields_set:
        fields["activity_override"] = values.get("activity_override")
    return fields


def resolve_effective_status(fields: dict, auto_status: str):
    """Whenever a write touches manual_status (set OR cleared via
    reset_status), the EFFECTIVE status -- not the raw manual_status
    field -- is what should get appended to StatusHistory, so a
    reset-to-auto is still a findable transition. Returns None when
    manual_status wasn't touched by this write at all, meaning:
    don't log a StatusHistory row.
    """
    if "manual_status" not in fields:
        return None
    return fields["manual_status"] or auto_status
