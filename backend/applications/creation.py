"""Manual, posting and retained-review creation share this transaction authority.

Lock order: workspace, request intent, category, posting, applications. PostgreSQL workspace row locks
serialize candidate review/allocation across creation routes. SQLite takes its write
lock before any transactional reads (no deferred read-to-write upgrade). No retry
is performed here; uncertain clients must deliberately reuse the original key.
"""
import hashlib
import json
import re
import secrets
from datetime import timedelta
from dataclasses import dataclass

from django.conf import settings
from django.db import OperationalError, connection, models, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from accounts.models import Workspace
from core.models import ApplicationRequestIntent
from postings.models import JobPosting, PostingApplicationConversion
from .models import Application, Override, StatusHistory
from .serializers import ApplicationSerializer
from documents.models import Category, CategoryMembership
from core.lifecycle import lifecycle_data, require_live


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def normalized(value):
    return " ".join(value.casefold().split())


def conflict(code, **details):
    return Response({"code": code, **details}, status=409)


def validate_request_key(key):
    if not key or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", key):
        raise ValidationError({"Idempotency-Key": "Supply a random opaque key of 16–128 letters, digits, underscores or hyphens."})


def lock_workspace(actor, workspace):
    """Must be called inside the allocation/membership transaction."""
    owned = Workspace.objects.filter(pk=workspace.pk, owner=actor)
    if connection.vendor == "sqlite":
        if not owned.update(name=models.F("name")):
            raise NotFound()
    elif not owned.select_for_update().exists():
        raise NotFound()


@dataclass(frozen=True)
class CreationOutcome:
    data: dict
    status: int


def review_digest(workspace_id, review_id, supplied):
    return digest({"version": 1, "kind": "review_create", "workspace_id": workspace_id,
                   "review_id": review_id, "fields": supplied})


def create_attempt(*, actor, workspace, key, supplied, values, posting_id=None, challenge=None, review_id=None):
    outcome = _execute_attempt(actor=actor, workspace=workspace, key=key, supplied=supplied,
        values=values, posting_id=posting_id, challenge=challenge, review_id=review_id)
    return Response(outcome.data, status=outcome.status)


def _execute_attempt(*, actor, workspace, key, supplied, values, posting_id, challenge, review_id):
    if review_id is not None:
        if not actor.is_authenticated:
            raise NotFound()
        if not isinstance(key, str):
            raise ValidationError({"Idempotency-Key": "Supply an opaque string key."})
        if challenge is not None and (not isinstance(challenge, str) or not challenge.isascii()
                                      or not 1 <= len(challenge) <= 64):
            raise ValidationError({"challenge": "Expected an opaque challenge token."})
    validate_request_key(key)
    if review_id is not None and posting_id is not None:
        raise ValidationError("Supply one creation source.")
    kind = "review_create" if review_id is not None else "posting" if posting_id is not None else "manual"
    intent_digest = (review_digest(workspace.pk, review_id, supplied) if review_id is not None else
        digest({"version": 1, "kind": kind, "posting_id": posting_id, "fields": supplied}))
    with transaction.atomic():
        lock_workspace(actor, workspace)
        # A continuation can only refer to an intent already issued under this
        # gate. Reject unknown keys before get_or_create can persist an orphan.
        if challenge is not None and not ApplicationRequestIntent.objects.filter(
                actor=actor, workspace=workspace, key=key).exists():
            return CreationOutcome({"code": "invalid_challenge"}, 409)
        intent, _ = ApplicationRequestIntent.objects.get_or_create(
            actor=actor, workspace=workspace, key=key,
            defaults={"digest": intent_digest, "kind": kind},
        )
        if intent.digest != intent_digest:
            return CreationOutcome({"code": "idempotency_key_reused"}, 409)
        review = None
        if review_id is not None:
            from . import review_creation
            review = review_creation.get_review(workspace, review_id)
        if intent.completed:
            if review is not None:
                return CreationOutcome(review_creation.replay(intent, review), 200)
            app = Application.objects.filter(pk=intent.application_id, workspace=workspace).first()
            if app is None:
                return CreationOutcome({"state": "removed", "portable_id": str(intent.result_portable_id)}, 200)
            return result(app, kind, replay=True)

        job = None
        data = dict(values)
        selected_candidate = None
        if review is not None:
            # Validate semantic input at the service boundary too. HTTP handling
            # must not be the only protection against conflicting supplied/values.
            from .serializers import ReviewCreateSerializer
            serializer = ReviewCreateSerializer(data=supplied)
            if not isinstance(supplied, dict) or set(supplied) - set(serializer.fields):
                raise ValidationError("Unknown review creation fields.")
            serializer.is_valid(raise_exception=True)
            if dict(serializer.validated_data) != supplied or values != supplied:
                raise ValidationError("Review creation input must be validated semantic fields.")
            data = {**supplied, "section": "applications"}
            selected_candidate = review_creation.admit(review, supplied.get("candidate_id"))
        category = None
        if data.get("category_id") is not None:
            category = Category.objects.select_for_update().filter(pk=data["category_id"], workspace=workspace).first()
            if category is None:
                raise NotFound()
        if category:
            require_live(category)
        if posting_id is not None:
            job = JobPosting.objects.select_for_update().filter(pk=posting_id, workspace=workspace, account__workspace=workspace).first()
            if job is None:
                raise NotFound()
            data["company"] = data.get("company", "").strip() or (job.company or "").strip()
            data["role_label"] = data.get("role_label", "").strip() or (job.title or "").strip()
            data["section"] = "applications"
        if not data.get("company"):
            raise ValidationError({"company": "This field is required."})
        status_value = data.get("status", "").strip()
        if status_value and status_value not in dict(Application.STATUS_CHOICES):
            raise ValidationError({"status": "Unknown status."})
        candidates = []
        applications = list(Application.objects.select_for_update().filter(workspace=workspace).order_by("pk"))
        overrides = {o.application_id: o for o in Override.objects.select_for_update().filter(application__workspace=workspace).order_by("application_id")}
        for app in applications:
            if normalized(app.company) == normalized(data["company"]) and normalized(app.role_label) == normalized(data.get("role_label", "")):
                override = overrides.get(app.pk)
                candidates.append({"id": app.pk, "portable_id": str(app.portable_id), "company": app.company,
                                   "role_label": app.role_label, "section": app.section,
                                   "archived": bool(override and override.archived), **lifecycle_data(app),
                                   "status": override.manual_status if override and override.manual_status else app.status,
                                   "date_applied": str(override.date_applied) if override and override.date_applied else None})
        conversions = list(PostingApplicationConversion.objects.filter(posting=job, workspace=workspace).order_by("pk").values_list("pk", "application_id", "application_portable_id")) if job else []
        # Only fingerprints are persisted, never candidate descriptors. Include the
        # complete visible candidate revision and posting fallback context.
        revision_context = {"candidates": candidates, "conversions": [[i, a, str(p)] for i, a, p in conversions],
                           "posting": [job.company, job.title, job.status] if job else None,
                           "category": [category.pk, str(category.portable_id), category.revision, category.lifecycle_revision] if category else None}
        extra = {}
        if review is not None:
            extra = review_creation.repeat_context(review)
            revision_context["review"] = {"id": review.pk, "digest": intent_digest,
                "disposition_revision": review_creation.current_disposition(review)["revision"], **extra}
        revision = digest(revision_context)
        if challenge is not None:
            if not intent.challenge_token or not secrets.compare_digest(challenge, intent.challenge_token):
                return CreationOutcome({"code": "invalid_challenge"}, 409)
            if intent.challenge_expires_at <= timezone.now():
                return CreationOutcome({"code": "challenge_expired"}, 409)
            if intent.challenge_revision != revision:
                return CreationOutcome({"code": "stale_challenge"}, 409)
        elif candidates or conversions or intent.challenge_token or any(extra.values()):
            # A caller can explicitly request renewed review by resubmitting the
            # same intent without a continuation token. Old tokens become invalid.
            intent.challenge_token = secrets.token_urlsafe(32)
            intent.challenge_revision = revision
            intent.challenge_expires_at = timezone.now() + timedelta(seconds=getattr(settings, "APPLICATION_CHALLENGE_TTL_SECONDS", 900))
            intent.save(update_fields=["challenge_token", "challenge_revision", "challenge_expires_at"])
            return CreationOutcome({"code": "new_attempt_confirmation_required", "challenge": intent.challenge_token,
                "expires_at": intent.challenge_expires_at.isoformat(), "candidates": candidates,
                **(extra if review is not None else {"prior_conversion_count": len(conversions)})}, 409)
        app = Application.objects.create(workspace=workspace, company=data["company"],
                                         role_label=data.get("role_label", ""), section=data.get("section", "applications"))
        if category:
            CategoryMembership.objects.create(application=app, category=category)
            app.category_revision = 1
            app.save(update_fields=["category_revision"])
        from applications.derivation import _derive_locked, record_transition, effective_status
        _derive_locked(app, record_history=False)
        previous_status = effective_status(app)
        if status_value:
            Override.objects.create(application=app, manual_status=status_value)
            app._state.fields_cache.pop("override", None)
            record_transition(app, previous_status, "review_create" if review is not None else "job_posting_apply" if job else "manual_create")
            _derive_locked(app, record_history=False)
        if job:
            PostingApplicationConversion.objects.create(workspace=workspace, posting=job, application=app,
                application_portable_id=app.portable_id, request_intent=intent, converted_at=timezone.now())
        intent.application = app
        intent.result_portable_id = app.portable_id
        creation_result = None
        if review is not None:
            creation_result = review_creation.finish(actor=actor, workspace=workspace, review=review,
                candidate=selected_candidate, intent=intent, app=app, supplied=supplied)
        intent.completed = True
        # Clear consumed review data; completed key replays cannot allocate again.
        intent.challenge_token = ""
        intent.challenge_revision = ""
        intent.challenge_expires_at = None
        intent.save()
        if creation_result is not None:
            return CreationOutcome(review_creation.result_data(creation_result, review), 201)
        return result(app, kind)


def result(app, kind, replay=False):
    body = {"ok": True, "application_id": app.pk, "portable_id": str(app.portable_id), **lifecycle_data(app)} if kind == "posting" else ApplicationSerializer(app).data
    return CreationOutcome(body, 200 if replay else 201)


def request_creation(request, workspace, serializer, posting_id=None, review_id=None):
    allowed = set(serializer.fields) | {"challenge"}
    if not isinstance(request.data, dict) or set(request.data) - allowed:
        raise ValidationError({"detail": "Unknown creation fields are not accepted."})
    token = request.data.get("challenge")
    if "challenge" in request.data and (
        not isinstance(token, str) or not token.isascii() or not 1 <= len(token) <= 64
    ):
        raise ValidationError({"challenge": "Expected an opaque challenge token."})
    serializer.is_valid(raise_exception=True)
    # Preserve omission versus explicit values, while comparing validated semantic
    # values rather than insignificant JSON whitespace/key order.
    supplied = {key: serializer.validated_data[key] for key in request.data if key != "challenge"}
    return create_attempt(actor=request.user, workspace=workspace,
                          key=request.headers.get("Idempotency-Key"), supplied=supplied,
                          values=serializer.validated_data, posting_id=posting_id, challenge=token, review_id=review_id)


class CreationContentionMixin:
    """Include SQLite admission reads in bounded allocation contention handling."""
    def handle_exception(self, exc):
        if ((getattr(self, "creation_action", False) or getattr(self, "action", None) in {"create", "apply", "category"}) and isinstance(exc, OperationalError)
                and connection.vendor == "sqlite" and "locked" in str(exc).lower()):
            return Response({"code": "creation_busy", "detail": "Database busy. Reconcile using the original request key."}, status=503)
        return super().handle_exception(exc)
