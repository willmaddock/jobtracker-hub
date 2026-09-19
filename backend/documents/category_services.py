"""Synchronous native category operations. No filesystem or lifecycle effects."""
import secrets
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from applications.creation import conflict, digest, lock_workspace, validate_request_key
from applications.models import Application
from core.models import ApplicationRequestIntent
from core.lifecycle import lifecycle_data, require_live
from .models import Category, CategoryMembership, CATEGORY_SECTIONS, normalized_category_name


def category_data(category):
    return {"id": category.pk, "workspace": category.workspace_id, "portable_id": str(category.portable_id),
            "name": category.name, "section": category.section, "archived": category.archived,
            "revision": category.revision, "provenance": category.provenance, **lifecycle_data(category)}


def ordered_categories(queryset):
    return sorted(queryset, key=lambda c: (CATEGORY_SECTIONS.index(c.section), normalized_category_name(c.name), c.pk))


def mutate_category(*, actor, workspace, key, supplied, values, category_id=None, challenge=None):
    validate_request_key(key)
    kind = "category_create" if category_id is None else "category_update"
    intent_digest = digest({"version": 1, "kind": kind, "category_id": category_id, "fields": supplied})
    with transaction.atomic():
        lock_workspace(actor, workspace)
        # Target lookup is scoped even when a client reuses another operation's key.
        category = None
        if category_id is not None:
            category = Category.objects.select_for_update().filter(workspace=workspace, pk=category_id).first()
            if category is None:
                raise NotFound()
        intent, _ = ApplicationRequestIntent.objects.get_or_create(actor=actor, workspace=workspace, key=key,
            defaults={"digest": intent_digest, "kind": kind})
        if intent.digest != intent_digest:
            return conflict("idempotency_key_reused")
        if intent.completed:
            result = Category.objects.filter(pk=intent.category_id, workspace=workspace).first()
            if result is None:
                return Response({"state": "removed", "portable_id": str(intent.result_portable_id)})
            return Response(category_data(result))
        if category:
            require_live(category)
        if category and values["expected_revision"] != category.revision:
            return conflict("stale_revision")
        name = values.get("name", category.name if category else "")
        rename = category is None or name != category.name
        candidates = [category_data(c) for c in ordered_categories(Category.objects.select_for_update().filter(workspace=workspace))
                      if rename and (category is None or c.pk != category.pk)
                      and normalized_category_name(c.name) == normalized_category_name(name)]
        # Do not retain names/descriptions in the request record.
        revision = digest({"candidates": candidates, "target_revision": category.revision if category else None})
        if challenge is not None:
            if not intent.challenge_token or not secrets.compare_digest(challenge, intent.challenge_token):
                return conflict("invalid_challenge")
            if intent.challenge_expires_at <= timezone.now():
                return conflict("challenge_expired")
            if intent.challenge_revision != revision:
                return conflict("stale_challenge")
        elif candidates or intent.challenge_token:
            intent.challenge_token = secrets.token_urlsafe(32)
            intent.challenge_revision = revision
            intent.challenge_expires_at = timezone.now() + timedelta(seconds=getattr(settings, "APPLICATION_CHALLENGE_TTL_SECONDS", 900))
            intent.save(update_fields=["challenge_token", "challenge_revision", "challenge_expires_at"])
            return conflict("duplicate_category_name", candidates=candidates, challenge=intent.challenge_token,
                            expires_at=intent.challenge_expires_at.isoformat())
        if category is None:
            category = Category.objects.create(workspace=workspace, name=name, section=values["section"])
        else:
            changes = {field: values[field] for field in ("name", "section", "archived")
                       if field in values and values[field] != getattr(category, field)}
            if changes:
                for field, value in changes.items():
                    setattr(category, field, value)
                category.revision += 1
                category.save(update_fields=[*changes, "revision"])
        intent.category = category
        intent.result_portable_id = category.portable_id
        intent.completed = True
        intent.challenge_token = ""
        intent.challenge_revision = ""
        intent.challenge_expires_at = None
        intent.save()
        return Response(category_data(category), status=201 if category_id is None else 200)


def assign_category(*, actor, workspace, application_id, category_id, expected_revision):
    with transaction.atomic():
        lock_workspace(actor, workspace)
        # Same category-before-application lock order as protected creation.
        category = None
        if category_id is not None:
            category = Category.objects.select_for_update().filter(pk=category_id, workspace=workspace).first()
            if category is None:
                raise NotFound()
        application = Application.objects.select_for_update().filter(pk=application_id, workspace=workspace).first()
        if application is None:
            raise NotFound()
        require_live(application)
        if category:
            require_live(category)
        if application.category_revision != expected_revision:
            return conflict("stale_revision")
        membership = CategoryMembership.objects.filter(application=application).first()
        current_id = membership.category_id if membership else None
        if current_id != category_id:
            if category is None:
                CategoryMembership.objects.filter(application=application).delete()
            else:
                CategoryMembership.objects.update_or_create(application=application, defaults={"category": category})
            application.category_revision += 1
            application.save(update_fields=["category_revision"])
        return Response({"id": application.pk, "category_id": category_id, "category_revision": application.category_revision})
