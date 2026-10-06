"""Read-only retained extraction evidence transport and bounded navigation."""
import base64
import binascii
import json
import re

from django.db import DatabaseError
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from core.workspace_scope import WorkspaceScopedMixin
from . import retained_extraction_inspection as inspection

CURSOR_KEYS = ("version", "workspace_id", "retained_message_id", "last_extraction_id")
MAX_TOKEN_LENGTH = 256
MAX_CURSOR_BYTES = 192


def encode_cursor(cursor):
    payload = {key: getattr(cursor, key) for key in CURSOR_KEYS}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate key")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("Non-finite number")


def decode_cursor(token):
    try:
        if (not token or len(token) > MAX_TOKEN_LENGTH
                or re.fullmatch(r"[A-Za-z0-9_-]+", token) is None):
            raise ValueError
        raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
        if len(raw) > MAX_CURSOR_BYTES:
            raise ValueError
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                             parse_constant=reject_constant)
        if type(payload) is not dict or set(payload) != set(CURSOR_KEYS):
            raise ValueError
        if type(payload["version"]) is not int or payload["version"] != 1:
            raise ValueError
        if any(type(payload[key]) is not int or not 0 < payload[key] <= inspection.MAX_ID
               for key in CURSOR_KEYS[1:]):
            raise ValueError
        cursor = inspection.RetainedExtractionEvidenceCursor(**payload)
        if encode_cursor(cursor) != token:
            raise ValueError
        return cursor
    except (ValueError, UnicodeError, binascii.Error):
        raise ValidationError({"detail": "Invalid extraction evidence query."}) from None


def navigation(query):
    limits, cursors = query.getlist("limit"), query.getlist("cursor")
    if ("retained_message_id" in query or len(limits) > 1 or len(cursors) > 1
            or (limits and limits[0] not in ("1", "2", "3", "4", "5"))):
        raise ValidationError({"detail": "Invalid extraction evidence query."})
    return int(limits[0]) if limits else 2, decode_cursor(cursors[0]) if cursors else None


def output_json(output):
    return {"output_id": output.output_id, "portable_id": output.portable_id,
            "position": output.position, "source": output.source, "title": output.title,
            "company": output.company, "location": output.location, "salary": output.salary,
            "employment_type": output.employment_type}


def operation_json(operation):
    return {"extraction_id": operation.extraction_id, "operation_id": operation.operation_id,
            "extractor_method": operation.extractor_method, "extractor_version": operation.extractor_version,
            "snapshot_version": operation.snapshot_version, "input_spec_json": operation.input_spec_json,
            "extracted_at": operation.extracted_at, "recorded_at": operation.recorded_at,
            "output_count": operation.output_count, "outputs": [output_json(o) for o in operation.outputs]}


def page_json(page):
    source = page.source
    return {"source": {"workspace_id": source.workspace_id, "retained_message_id": source.retained_message_id,
                       "retained_message_portable_id": source.retained_message_portable_id,
                       "representation_version": source.representation_version, "source_eligible": source.source_eligible},
            "operations": [operation_json(o) for o in page.operations], "has_more": page.has_more,
            "next_cursor": encode_cursor(page.next_cursor) if page.next_cursor is not None else None,
            "consistency": page.consistency}


class RetainedExtractionEvidenceView(WorkspaceScopedMixin, APIView):
    permission_classes = [IsAuthenticated]
    renderer_classes = [JSONRenderer]
    http_method_names = ["get", "head", "options"]

    def get(self, request, workspace_id, retained_message_id):
        limit, cursor = navigation(request.query_params)
        page = inspection.read_retained_extraction_evidence(
            actor=request.user, workspace=self.get_workspace(),
            retained_message_id=retained_message_id, cursor=cursor, limit=limit)
        return Response(page_json(page))

    def handle_exception(self, exc):
        if isinstance(exc, DatabaseError):
            return Response({"detail": "Unable to inspect extraction evidence.", "code": "request_failed"}, status=500)
        return super().handle_exception(exc)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response
