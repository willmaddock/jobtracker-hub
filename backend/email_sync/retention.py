"""Explicit relevance-qualified retention, representation/comparison version 1.

No providers, workflow side effects, or automatic retries. Lock order is Workspace
(the existing SQLite write gate / PostgreSQL row lock), mailbox, key, message.
All accepted source facts are immutable; conflicting variants are append-only.
"""
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone as dt_timezone

from django.conf import settings
from django.db import transaction
from rest_framework.exceptions import NotFound, ValidationError

from accounts.models import Workspace
from applications.creation import lock_workspace
from .models import MailboxLineage, RetainedMessage, RetainedObservation, RetentionKey

VERSION = 1
MAX_INPUT_BYTES = 2 * 1024 * 1024
DEFAULT_TEXT_BYTES = 128 * 1024
DEFAULT_HTML_BYTES = 256 * 1024
PROVIDERS = {"gmail", "outlook", "imap"}
HEADERS = {"date", "message-id", "in-reply-to", "references", "mime-version", "content-type", "content-transfer-encoding"}
ADDRESS_ROLES = {"from", "sender", "reply_to", "to", "cc", "bcc"}


def invalid():
    # Never include supplied content, locators, or provenance in errors/logs.
    raise ValidationError("Invalid retained-email observation.")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def text(value, limit, *, empty=True):
    if not isinstance(value, str) or (not empty and not value) or "\x00" in value:
        invalid()
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError:
        invalid()
    if size > limit:
        invalid()
    return value


def shape(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or not set(required) <= set(value):
        invalid()


def instant(value):
    text(value, 64, empty=False)
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            invalid()
        return parsed.astimezone(dt_timezone.utc).isoformat()
    except (ValueError, OverflowError):
        invalid()


def source_time(value, *, received=False):
    shape(value, {"precision", "value", "source"}, {"precision", "value", "source"})
    precision, raw, source = value["precision"], value["value"], value["source"]
    text(precision, 16, empty=False)
    text(source, 64, empty=False)
    if received and source not in {"gmail_internal_date", "graph_received_datetime", "imap_internaldate", "unknown"}:
        invalid()
    offset_seconds = None
    if precision == "instant":
        normalized_instant = instant(raw)
        offset_seconds = int(datetime.fromisoformat(raw).utcoffset().total_seconds())
        raw = normalized_instant
    elif precision == "date":
        try:
            raw = date.fromisoformat(text(raw, 10)).isoformat()
        except ValueError:
            invalid()
    elif precision == "uncertain":
        raw = text(raw, 128, empty=False)
    elif precision != "unknown" or raw is not None:
        invalid()
    if source == "unknown" and precision != "unknown":
        invalid()
    result = {"precision": precision, "value": raw, "source": source}
    if offset_seconds is not None:
        result["source_utc_offset_seconds"] = offset_seconds
    return result


def body(value, limit):
    shape(value, {"value", "completeness", "reason"}, {"value", "completeness"})
    state = text(value["completeness"], 16, empty=False)
    reason = text(value.get("reason", ""), 256)
    if state not in {"complete", "partial", "unavailable"}:
        invalid()
    if state == "unavailable":
        if value["value"] is not None:
            invalid()
        return {"value": None, "completeness": state, "reason": reason}
    raw = text(value["value"], MAX_INPUT_BYTES)
    if state == "partial" and not reason:
        invalid()
    # Decoded text line endings are equivalent; HTML remains byte-for-byte source.
    encoded = raw.encode("utf-8")
    output = {"value": raw, "completeness": state, "reason": reason}
    if len(encoded) > limit:
        kept = encoded[:limit].decode("utf-8", errors="ignore")
        output.update(value=kept, completeness="partial", reason="retention_byte_limit",
                      truncation={"location": "utf8_prefix", "retained_bytes": len(kept.encode()),
                                  "original_bytes": len(encoded), "original_digest": hashlib.sha256(encoded).hexdigest(),
                                  "source_completeness": state, "source_reason": reason})
    return output


def normalize(supplied):
    shape(supplied, {"reason", "observed_at", "mailbox_id", "source", "content"}, {"reason", "observed_at", "content"})
    text(supplied["reason"], 32, empty=False)
    if supplied["reason"] not in {"application_evidence", "discovery_review", "posting_source"}:
        invalid()
    # Reject an over-limit observation atomically; no partial state on invalid input.
    try:
        if len(json.dumps(supplied, ensure_ascii=False).encode("utf-8")) > MAX_INPUT_BYTES:
            invalid()
    except (TypeError, ValueError, UnicodeError, RecursionError):
        invalid()
    mailbox_id = supplied.get("mailbox_id")
    if mailbox_id is not None and (type(mailbox_id) is not int or mailbox_id <= 0):
        invalid()
    source = supplied.get("source")
    if source is not None:
        fields = {"provider", "kind", "value", "folder", "stability"}
        shape(source, fields, {"provider"})
        source = {field: source.get(field) for field in fields}
        text(source["provider"], 16, empty=False)
        if source["provider"] not in PROVIDERS:
            invalid()
        for field, limit in [("kind", 32), ("value", 512), ("folder", 512), ("stability", 128)]:
            if source[field] is not None:
                text(source[field], limit, empty=field == "folder")
        expected = {"gmail": "gmail_message_id", "outlook": "graph_immutable_id", "imap": "imap_uid"}
        if source["kind"] is not None and source["kind"] != expected[source["provider"]]:
            invalid()
        if source["provider"] == "imap":
            if source["folder"] == "":
                invalid()
            if source["value"] is not None and (not re.fullmatch(r"[1-9][0-9]{0,9}", source["value"]) or int(source["value"]) > 4294967295):
                invalid()
            if source["stability"] is not None and (not re.fullmatch(r"uidvalidity:[1-9][0-9]{0,9}", source["stability"]) or int(source["stability"].split(":")[1]) > 4294967295):
                invalid()
        elif source["folder"] not in (None, "") or source["stability"] not in (None, "v1"):
            invalid()
    content = supplied["content"]
    fields = {"subject", "addresses", "headers", "text", "html", "header_sent", "provider_received", "provenance", "conversation_id"}
    shape(content, fields, fields - {"conversation_id"})
    subject = content["subject"]
    if subject is not None:
        subject = text(subject, 4096)
    addresses = content["addresses"]
    shape(addresses, ADDRESS_ROLES)
    normalized_addresses = {}
    for role, entries in addresses.items():
        if not isinstance(entries, list) or len(entries) > 100:
            invalid()
        normalized_addresses[role] = []
        for entry in entries:
            shape(entry, {"name", "address"}, {"name", "address"})
            normalized_addresses[role].append({"name": text(entry["name"], 1024), "address": text(entry["address"], 1024)})
    headers = content["headers"]
    if not isinstance(headers, list) or len(headers) > 100:
        invalid()
    normalized_headers = []
    for header in headers:
        if not isinstance(header, list) or len(header) != 2:
            invalid()
        name = text(header[0], 64).lower()
        if name not in HEADERS:
            invalid()
        normalized_headers.append([name, text(header[1], 8192)])
    provenance = content["provenance"]
    # No arbitrary provider blob or auth/credential keys.
    shape(provenance, {"method", "version"}, {"method", "version"})
    provenance = {name: text(value, 128, empty=False) for name, value in provenance.items()}
    text_limit = getattr(settings, "RETAINED_EMAIL_TEXT_BYTES", DEFAULT_TEXT_BYTES)
    html_limit = getattr(settings, "RETAINED_EMAIL_HTML_BYTES", DEFAULT_HTML_BYTES)
    if any(type(n) is not int or not 1 <= n <= DEFAULT_HTML_BYTES for n in (text_limit, html_limit)):
        invalid()
    plain = dict(content["text"]) if isinstance(content["text"], dict) else content["text"]
    if isinstance(plain, dict) and isinstance(plain.get("value"), str):
        plain["value"] = plain["value"].replace("\r\n", "\n").replace("\r", "\n")
    normalized_content = {
        "version": VERSION, "subject": subject, "addresses": normalized_addresses,
        "headers": normalized_headers, "text": body(plain, text_limit), "html": body(content["html"], html_limit),
        "header_sent": source_time(content["header_sent"]), "provider_received": source_time(content["provider_received"], received=True),
        "provenance": provenance, "conversation_id": text(content.get("conversation_id", ""), 512),
    }
    return {"version": VERSION, "reason": supplied["reason"], "observed_at": instant(supplied["observed_at"]),
            "mailbox_id": mailbox_id, "source": source, "content": normalized_content}


def authorize(actor, workspace):
    if not actor.is_authenticated or not Workspace.objects.filter(pk=workspace.pk, owner=actor).exists():
        raise NotFound()


def establish_mailbox(*, actor, workspace, provider, evidence):
    """Register explicitly established lineage, never infer/reconnect by address.

Internal caller supplies externally established proof; no provider verification is
performed here. Reuse the returned ID, not this allocator, on observation retries.
"""
    authorize(actor, workspace)
    text(provider, 16, empty=False)
    if provider not in PROVIDERS:
        invalid()
    shape(evidence, {"method", "reference"}, {"method", "reference"})
    evidence = {k: text(v, 512, empty=False) for k, v in evidence.items()}
    with transaction.atomic():
        lock_workspace(actor, workspace)
        return MailboxLineage.objects.create(workspace=workspace, provider=provider, evidence=evidence)


@dataclass(frozen=True)
class RetentionResult:
    observation_id: int
    message_id: int | None
    state: str
    replay: bool
    eligible: bool


def result(observation, replay):
    conflicted = observation.key.has_conflict or (observation.message_id and observation.message.has_conflict)
    state = "conflict" if conflicted else observation.state
    return RetentionResult(observation.pk, observation.message_id, state, replay, state == "retained")


def retain_observation(*, actor, workspace, key, observation):
    authorize(actor, workspace)
    text(key, 128, empty=False)
    payload = normalize(observation)
    fingerprint = digest(payload)
    with transaction.atomic():
        lock_workspace(actor, workspace)
        mailbox = None
        if payload["mailbox_id"] is not None:
            mailbox = MailboxLineage.objects.select_for_update().filter(pk=payload["mailbox_id"], workspace=workspace).first()
            if mailbox is None:
                raise NotFound()
            if payload["source"] and payload["source"]["provider"] != mailbox.provider:
                invalid()
            received_source = payload["content"]["provider_received"]["source"]
            expected_received = {"gmail": "gmail_internal_date", "outlook": "graph_received_datetime", "imap": "imap_internaldate"}
            if received_source not in {"unknown", expected_received[mailbox.provider]}:
                invalid()
        binding, _ = RetentionKey.objects.get_or_create(workspace=workspace, key=key, defaults={"initial_digest": fingerprint})
        prior = RetainedObservation.objects.select_related("key", "message").filter(key=binding, digest=fingerprint).first()
        if prior:
            return result(prior, True)
        message = None
        state, reason = "unresolved", ""
        if binding.initial_digest != fingerprint:
            state, reason = "conflict", "observation_key_reused"
            RetentionKey.objects.filter(pk=binding.pk).update(has_conflict=True)
            binding.has_conflict = True
            initial = binding.observations.get(digest=binding.initial_digest)
            message = initial.message
            if message:
                RetainedMessage.objects.filter(pk=message.pk).update(has_conflict=True)
                message.has_conflict = True
        elif mailbox and payload["source"] and all(value is not None for value in payload["source"].values()):
            source = payload["source"]
            content_digest = digest(payload["content"])
            message, created = RetainedMessage.objects.get_or_create(
                workspace=workspace, mailbox=mailbox, provider=source["provider"], locator_kind=source["kind"],
                locator_value=source["value"], folder=source["folder"], stability=source["stability"],
                defaults={"content": payload["content"], "content_digest": content_digest},
            )
            state = "retained"
            if not created and message.content_digest != content_digest:
                state, reason = "conflict", "source_content_conflict"
                RetainedMessage.objects.filter(pk=message.pk).update(has_conflict=True)
                message.has_conflict = True
        row = RetainedObservation.objects.create(workspace=workspace, key=binding, message=message, mailbox=mailbox,
            digest=fingerprint, payload=payload, state=state, conflict_reason=reason, observed_at=payload["observed_at"])
        return result(row, False)
