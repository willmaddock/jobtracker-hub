"""
Celery tasks for email_sync (Phase 10 background task runner --
closes the "no background task runner" gap flagged in
docs/DJANGO_MIGRATION_PLAN.md's Phase 9 Known gaps and
docs/DJANGO_BACKEND_HANDOFF.md §4).

Two tasks, deliberately kept as thin wrappers around code that's
already tested elsewhere:

- sync_account_task(account_id) is the per-account unit of work --
  the same provider-resolve-then-sync_account() sequence
  EmailAccountSyncView.post() already runs synchronously
  (email_sync/views.py), just callable via .delay()/.apply_async()
  instead of inline in a request/response cycle. Takes an id, not an
  EmailAccount instance: Celery task arguments are serialized
  (JSON, per CELERY_TASK_SERIALIZER in config/settings/base.py) onto
  the broker, so a live model instance either fails to serialize or
  goes stale by the time a worker actually picks the message up.
- sync_all_accounts_task() is the scheduled entry point
  (CELERY_BEAT_SCHEDULE in config/settings/base.py) and also what
  EmailAccountSyncAllView (email_sync/views.py) dispatches to for a
  user-triggered "sync everything" -- it does no syncing itself, only
  looks up every currently-connected EmailAccount and fans out one
  sync_account_task.delay(account.id) per account. Fanning out rather
  than looping and calling sync_account() directly, in-process, means
  one slow/stuck account can't block every other account's turn --
  each dispatched task is its own independent unit on the queue, with
  its own retry/failure/observability story.

Neither task does the workspace__owner=request.user filtering
EmailAccountSyncView does -- there is no request or user in a
scheduled/background context, just "every connected account," same
as any other system-initiated (not user-initiated) job.
EmailAccountSyncAllView is what applies that per-user scoping, on the
list of ids it hands each dispatched task.

Failure handling: sync_account() itself already turns a
ProviderAuthError into account.status="blocked" plus a non-raising
SyncResult (see its own docstring) -- that path needs no extra
handling here. What sync_account_task additionally guards against,
that the synchronous view doesn't have to worry about, is the account
or its provider having disappeared/become unregistered in the gap
between sync_all_accounts_task looking it up and a worker actually
running this task later (EmailAccount.DoesNotExist -- e.g. the
account was deleted in the interim; ProviderError -- e.g. a legacy
mail_app/icloud row with no real provider). Both are logged and
returned as a non-ok result rather than raised, since Celery's
default retry-on-exception behavior is the wrong shape for "this
account will never sync," not "this attempt happened to fail and a
retry might succeed."
"""
from __future__ import annotations

import logging

from celery import shared_task

from .models import EmailAccount
from .providers import ProviderError, get_provider
from .sync_service import sync_account

logger = logging.getLogger(__name__)


@shared_task(name="email_sync.tasks.sync_account_task")
def sync_account_task(account_id: int) -> dict:
    """Run one sync_service.sync_account() pass for the EmailAccount
    with this id, resolving its provider first. Returns a plain dict
    (a Celery result backend needs a serializable value, not a
    SyncResult dataclass instance) in the same shape
    EmailAccountSyncView.post() already returns as JSON, so a future
    status/history page could render either path's outcome the same
    way without a separate serializer for each."""
    try:
        account = EmailAccount.objects.get(pk=account_id)
    except EmailAccount.DoesNotExist:
        logger.warning("sync_account_task: EmailAccount %s no longer exists", account_id)
        return {"account_id": account_id, "ok": False, "error": "account not found"}

    if account.status == "disconnected":
        return {"account_id": account_id, "ok": False, "error": "account is disconnected"}

    try:
        provider = get_provider(account.provider)
    except ProviderError as exc:
        logger.warning(
            "sync_account_task: no provider for account %s (%s): %s",
            account_id,
            account.provider,
            exc,
        )
        return {"account_id": account_id, "ok": False, "error": str(exc)}

    result = sync_account(account, provider)
    return {
        "account_id": result.account_id,
        "ok": result.ok,
        "error": result.error,
        "messages_seen": result.messages_seen,
        "new_matches": result.new_matches,
        "new_discoveries": result.new_discoveries,
        "skipped_existing": result.skipped_existing,
        "status": account.status,
    }


@shared_task(name="email_sync.tasks.sync_all_accounts_task")
def sync_all_accounts_task() -> dict:
    """Fan out one sync_account_task per currently-connected
    EmailAccount, across every workspace -- the CELERY_BEAT_SCHEDULE
    entry point (config/settings/base.py). Dispatches rather than
    syncing inline so this returns immediately regardless of how many
    accounts exist or how slow any one of them is."""
    account_ids = list(
        EmailAccount.objects.filter(status="connected").values_list("id", flat=True)
    )
    for account_id in account_ids:
        sync_account_task.delay(account_id)
    return {"dispatched": len(account_ids)}
