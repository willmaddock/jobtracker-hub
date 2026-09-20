"""Read-only JSON inspection; original HTML is never returned or rendered."""
from copy import deepcopy

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from core.workspace_scope import WorkspaceScopedMixin
from .models import MailboxLineage, RetainedMessage, RetainedObservation


def readable(content):
    content = deepcopy(content)
    html = content["html"]
    content["html"] = {k: v for k, v in html.items() if k != "value"}
    content["html"]["available"] = html["value"] is not None
    return content


class Inspection(WorkspaceScopedMixin, APIView):
    permission_classes = [IsAuthenticated]
    renderer_classes = [JSONRenderer]
    http_method_names = ["get", "head", "options"]

    def page(self, queryset, serialize):
        cursor = self.request.query_params.get("after", "0")
        if not cursor.isascii() or not cursor.isdigit() or len(cursor) > 19 or int(cursor) > 9223372036854775807:
            raise ValidationError("Invalid inspection cursor.")
        rows = list(queryset.filter(pk__gt=int(cursor)).order_by("pk")[:51])
        return Response({"results": [serialize(row) for row in rows[:50]],
                         "next_after": rows[49].pk if len(rows) > 50 else None})


def message_summary(row):
    return {"id": row.pk, "portable_id": str(row.portable_id), "mailbox_id": row.mailbox_id,
            "state": "conflict" if row.has_conflict else "retained", "eligible": not row.has_conflict,
            "retained_at": row.retained_at, "representation_version": row.representation_version}


def observation_summary(row):
    conflict = row.key.has_conflict or (row.message_id and row.message.has_conflict)
    state = "conflict" if conflict else row.state
    return {"id": row.pk, "message_id": row.message_id, "mailbox_id": row.mailbox_id,
            "state": state, "recorded_state": row.state, "eligible": state == "retained",
            "conflict_reason": row.conflict_reason, "key_has_conflict": row.key.has_conflict,
            "observed_at": row.observed_at, "retained_at": row.retained_at}


class RetainedMessageList(Inspection):
    def get(self, request, workspace_id):
        return self.page(RetainedMessage.objects.filter(workspace=self.get_workspace(), mailbox__workspace=self.get_workspace()), message_summary)


class RetainedMessageDetail(Inspection):
    def get(self, request, workspace_id, pk):
        row = get_object_or_404(RetainedMessage, pk=pk, workspace=self.get_workspace(), mailbox__workspace=self.get_workspace())
        return Response({**message_summary(row), "content": readable(row.content),
            "source": {"provider": row.provider, "kind": row.locator_kind, "value": row.locator_value,
                       "folder": row.folder, "stability": row.stability}})


def scoped_observations(workspace):
    return RetainedObservation.objects.filter(workspace=workspace, key__workspace=workspace).filter(
        Q(mailbox__isnull=True) | Q(mailbox__workspace=workspace)
    ).filter(Q(message__isnull=True) | Q(message__workspace=workspace, message__mailbox__workspace=workspace)).select_related("key", "message")


class RetainedObservationList(Inspection):
    def get(self, request, workspace_id):
        rows = scoped_observations(self.get_workspace())
        message_id = request.query_params.get("message_id")
        if message_id is not None:
            if not message_id.isascii() or not message_id.isdigit() or len(message_id) > 19 or int(message_id) > 9223372036854775807:
                raise ValidationError("Invalid message reference.")
            get_object_or_404(RetainedMessage, pk=int(message_id), workspace=self.get_workspace(), mailbox__workspace=self.get_workspace())
            rows = rows.filter(message_id=int(message_id))
        return self.page(rows, observation_summary)


class RetainedObservationDetail(Inspection):
    def get(self, request, workspace_id, pk):
        row = get_object_or_404(scoped_observations(self.get_workspace()), pk=pk)
        payload = deepcopy(row.payload)
        payload["content"] = readable(payload["content"])
        return Response({**observation_summary(row), "payload": payload})


class MailboxLineageDetail(Inspection):
    def get(self, request, workspace_id, pk):
        row = get_object_or_404(MailboxLineage, pk=pk, workspace=self.get_workspace())
        return Response({"id": row.pk, "portable_id": str(row.portable_id), "provider": row.provider,
                         "evidence": row.evidence, "established_at": row.established_at})
