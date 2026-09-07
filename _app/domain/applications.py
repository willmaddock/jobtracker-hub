"""
Override-write rules for a single application (save_override) and for
bulk application updates (bulk_override) -- what fields actually get
written to overrides.db given a request's model_fields_set, and whether
that write should also log a status_history row.

Extracted from api.py's save_override/bulk_override route bodies. This is
the piece that was flagged as the clearest extraction target in the whole
file: real domain rules (the model_fields_set field-diffing, the
date_applied_source provenance-clearing rule, and the manual-status ->
status_history trigger) were sitting directly inline in two HTTP handlers
with zero separation from request parsing and DB I/O.

No FastAPI or pydantic import here on purpose -- these functions take a
plain `fields_set: set[str]` (a pydantic model's `.model_fields_set`) and
a plain `values: dict` (`.model_dump()`), not the request model itself, so
the rules are testable with a bare dict/set and no HTTP machinery at all.
"""

from __future__ import annotations


def _resolve_manual_status(fields_set: set, reset_status: bool, manual_status) -> dict:
    """Shared by both routes below. Use model_fields_set (not `is not
    None`) so an explicitly-sent null (e.g. "Mark followed up" clearing
    next_action/next_action_date) is actually applied instead of being
    indistinguishable from "field not sent at all" and silently dropped by
    upsert_override's merge. reset_status always wins over a manual_status
    sent in the same request."""
    if reset_status:
        return {"manual_status": None}
    if "manual_status" in fields_set:
        return {"manual_status": manual_status}
    return {}


def compute_override_fields(fields_set: set, values: dict, reset_status: bool) -> dict:
    """save_override's full field-diffing rule for a single application.

    fields_set: req.model_fields_set -- which fields the caller actually
        sent, vs. left at their pydantic default.
    values: req.model_dump() -- the raw values for those fields.
    reset_status: req.reset_status -- explicit "clear manual_status" flag,
        distinct from just not sending manual_status at all.
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
        fields["archived"] = int(v) if v is not None else 0
    if "snoozed_until" in fields_set:
        fields["snoozed_until"] = values.get("snoozed_until")
    if "activity_override" in fields_set:
        fields["activity_override"] = values.get("activity_override")
    return fields


def compute_bulk_override_fields(fields_set: set, values: dict, reset_status: bool) -> dict:
    """bulk_override's field-diffing rule -- deliberately a different,
    smaller field set than compute_override_fields above (no notes,
    date_applied, or date_applied_source: bulk actions are status/archive/
    snooze/next-action only, never a per-item notes or date edit)."""
    fields: dict = dict(_resolve_manual_status(fields_set, reset_status, values.get("manual_status")))
    if "archived" in fields_set:
        v = values.get("archived")
        fields["archived"] = int(v) if v is not None else 0
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
    """Item 7: whenever a write touches manual_status (set OR cleared via
    reset_status), the EFFECTIVE status -- not the raw manual_status field
    -- is what should get logged to status_history, so a reset-to-auto is
    still a findable transition (see overrides_store.py). Returns None
    when manual_status wasn't touched by this write at all, meaning: don't
    log a status_history row."""
    if "manual_status" not in fields:
        return None
    return fields["manual_status"] or auto_status
