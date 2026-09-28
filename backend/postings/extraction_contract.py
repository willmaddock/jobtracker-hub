"""Pure, bounded recording contract. No parser execution or item identity.

Version 1 names the job-alert rules at 6863f277. Semantic parser changes need a
new extractor version; refactors do not. Input preparation and snapshot formats
have separate versions. Keep historical contracts recognizable on evolution.
"""
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

EXTRACTOR_METHOD = "job_alert_rules"
EXTRACTOR_VERSION = "1"
SNAPSHOT_VERSION = 1
INPUT_SPEC_VERSION = 1
INPUT_TRANSFORM_METHOD = "retained_text_arguments"
INPUT_TRANSFORM_VERSION = "1"
MAX_OUTPUTS = 1000
MAX_INPUT_SPEC_BYTES = 2048
MAX_PAYLOAD_BYTES = 2 * 1024 * 1024
SOURCES = frozenset({"linkedin", "handshake", "lensa", "indeed", "honeywell",
                     "jobs2web", "awseducate", "builtin", "symplicity"})
FIELDS = frozenset({"source", "title", "company", "location", "salary", "employment_type"})
STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
                   r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z")


class InvalidExtraction(ValueError):
    def __init__(self):
        super().__init__("Invalid posting extraction.")


def require(condition):
    if not condition:
        raise InvalidExtraction()


def shape(value, keys):
    require(type(value) is dict and set(value) == set(keys))


def text(value, limit, nullable=False):
    if nullable and value is None:
        return
    require(type(value) is str and "\x00" not in value)
    try:
        require(len(value.encode("utf-8")) <= limit)
    except UnicodeError:
        raise InvalidExtraction() from None


def canonical_json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise InvalidExtraction() from None


def digest(value):
    return hashlib.sha256(canonical_json(value)).hexdigest()


def operation_uuid(value):
    try:
        parsed = value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise InvalidExtraction() from None
    require(isinstance(value, uuid.UUID) or (type(value) is str and str(parsed) == value))
    require(parsed.variant == uuid.RFC_4122 and parsed.version == 4)
    return parsed


def timestamp(value):
    text(value, 64)
    require(STAMP.fullmatch(value) is not None)
    # datetime accepts some overflowing offset components; RFC3339 does not.
    if not value.endswith("Z"):
        require(int(value[-5:-3]) <= 23 and int(value[-2:]) <= 59)
    try:
        instant = datetime.fromisoformat(value).astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise InvalidExtraction() from None
    return instant.isoformat(timespec="microseconds")


def validate_spec(spec):
    shape(spec, {"version", "representation_version", "selectors", "transform"})
    for field in ("version", "representation_version"):
        require(type(spec[field]) is int and spec[field] == 1)
    selectors = spec["selectors"]
    shape(selectors, {"sender", "subject", "body"})
    require(selectors["subject"] == "content.subject" and selectors["body"] == "content.text.value")
    sender = selectors["sender"]
    if sender is not None:
        shape(sender, {"role", "index"})
        require(type(sender["role"]) is str and sender["role"] in {"from", "sender"})
        require(type(sender["index"]) is int and 0 <= sender["index"] <= 99)
    shape(spec["transform"], {"method", "version"})
    require(spec["transform"] == {"method": INPUT_TRANSFORM_METHOD, "version": INPUT_TRANSFORM_VERSION})
    require(len(canonical_json(spec)) <= MAX_INPUT_SPEC_BYTES)


def validate_fields(fields):
    shape(fields, FIELDS)
    text(fields["source"], 64)
    require(fields["source"] in SOURCES)
    for key in FIELDS - {"source"}:
        text(fields[key], 4096, nullable=True)


def validate_envelope(operation_id, method, version, spec, extracted_at, outputs):
    operation_id = operation_uuid(operation_id)
    require(type(method) is str and type(version) is str)
    require((method, version) == (EXTRACTOR_METHOD, EXTRACTOR_VERSION))
    validate_spec(spec)
    stamp = timestamp(extracted_at)
    require(type(outputs) is list and len(outputs) <= MAX_OUTPUTS)
    for fields in outputs:
        validate_fields(fields)
    payload = {"operation_id": str(operation_id), "extractor_method": method,
               "extractor_version": version, "snapshot_version": SNAPSHOT_VERSION,
               "input_spec": spec, "extracted_at": stamp,
               "outputs": [{"position": n, "fields": fields} for n, fields in enumerate(outputs)]}
    encoded = canonical_json(payload)
    require(len(encoded) <= MAX_PAYLOAD_BYTES)
    # Detach nested caller-owned objects before transactional processing.
    return json.loads(encoded)


def validate_body(body):
    require(type(body) is dict)
    require(set(body) in ({"value", "completeness", "reason"},
                         {"value", "completeness", "reason", "truncation"}))
    text(body["completeness"], 16)
    state = body["completeness"]
    require(state in {"complete", "partial", "unavailable"})
    text(body["reason"], 256)
    if state == "unavailable":
        require(body["value"] is None and "truncation" not in body)
    else:
        text(body["value"], MAX_PAYLOAD_BYTES)
    if state == "partial":
        require(bool(body["reason"]))
    if "truncation" in body:
        trunc = body["truncation"]
        shape(trunc, {"location", "retained_bytes", "original_bytes", "original_digest",
                      "source_completeness", "source_reason"})
        require(state == "partial" and body["reason"] == "retention_byte_limit")
        require(trunc["location"] == "utf8_prefix")
        require(type(trunc["retained_bytes"]) is int and type(trunc["original_bytes"]) is int)
        require(trunc["retained_bytes"] == len(body["value"].encode("utf-8"))
                and trunc["original_bytes"] > trunc["retained_bytes"])
        text(trunc["original_digest"], 64)
        require(re.fullmatch(r"[0-9a-f]{64}", trunc["original_digest"]) is not None)
        require(type(trunc["source_completeness"]) is str
                and trunc["source_completeness"] in {"complete", "partial"})
        text(trunc["source_reason"], 256)


def validate_source_time(value, *, received_provider=None):
    require(type(value) is dict)
    require(set(value) in ({"precision", "value", "source"},
                          {"precision", "value", "source", "source_utc_offset_seconds"}))
    text(value["precision"], 16)
    text(value["source"], 64)
    if received_provider is not None:
        # Semantic parity with retention.source_time(received=True) and
        # retain_observation's mailbox/provider admission. Retention owns policy.
        receipt_sources = {"gmail": "gmail_internal_date", "outlook": "graph_received_datetime",
                           "imap": "imap_internaldate"}
        require(type(received_provider) is str and received_provider in receipt_sources)
        require(value["source"] in {"unknown", receipt_sources[received_provider]})
    precision = value["precision"]
    require(precision in {"instant", "date", "uncertain", "unknown"})
    require(value["source"] != "unknown" or precision == "unknown")
    require(("source_utc_offset_seconds" in value) == (precision == "instant"))
    if precision == "unknown":
        require(value["value"] is None)
    elif precision == "instant":
        timestamp(value["value"])
    elif precision == "date":
        text(value["value"], 10)
        try:
            require(datetime.strptime(value["value"], "%Y-%m-%d").date().isoformat() == value["value"])
        except ValueError:
            raise InvalidExtraction() from None
    else:
        text(value["value"], 128)
        if received_provider is not None:
            require(bool(value["value"]))
    if "source_utc_offset_seconds" in value:
        offset = value["source_utc_offset_seconds"]
        require(precision == "instant" and type(offset) is int and -86400 < offset < 86400)


def validate_source_content(content, representation_version, content_digest, *, provider):
    """Validate persisted v1 shape without re-normalizing or truncating evidence."""
    require(type(representation_version) is int and representation_version == 1)
    shape(content, {"version", "subject", "addresses", "headers", "text", "html",
                    "header_sent", "provider_received", "provenance", "conversation_id"})
    require(type(content["version"]) is int and content["version"] == representation_version)
    text(content["subject"], 4096, nullable=True)
    addresses = content["addresses"]
    require(type(addresses) is dict and set(addresses) <= {"from", "sender", "reply_to", "to", "cc", "bcc"})
    for entries in addresses.values():
        require(type(entries) is list and len(entries) <= 100)
        for entry in entries:
            shape(entry, {"name", "address"})
            text(entry["name"], 1024)
            text(entry["address"], 1024)
    headers = content["headers"]
    require(type(headers) is list and len(headers) <= 100)
    for header in headers:
        require(type(header) is list and len(header) == 2)
        text(header[0], 64)
        require(header[0] in {"date", "message-id", "in-reply-to", "references", "mime-version",
                              "content-type", "content-transfer-encoding"})
        text(header[1], 8192)
    validate_body(content["text"])
    validate_body(content["html"])
    validate_source_time(content["header_sent"])
    validate_source_time(content["provider_received"], received_provider=provider)
    shape(content["provenance"], {"method", "version"})
    for value in content["provenance"].values():
        text(value, 128)
        require(bool(value))
    text(content["conversation_id"], 512)
    require(type(content_digest) is str and digest(content) == content_digest)


def resolve_selectors(spec, content):
    """Return declared arguments only; never invoke the parser."""
    validate_spec(spec)
    require(spec["representation_version"] == content["version"])
    sender = spec["selectors"]["sender"]
    if sender is None:
        require(not content["addresses"].get("from") and not content["addresses"].get("sender"))
        address = None
    else:
        entries = content["addresses"].get(sender["role"], [])
        require(sender["index"] < len(entries))
        address = entries[sender["index"]]["address"]
    return address, content["subject"], content["text"]["value"]


def replay_digest(envelope, source):
    payload = {"digest_version": 1, "source": source, **envelope}
    encoded = canonical_json(payload)
    require(len(encoded) <= MAX_PAYLOAD_BYTES)
    return hashlib.sha256(encoded).hexdigest()
