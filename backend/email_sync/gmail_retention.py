"""Gmail sync's internal bridge to the existing retained-source authority.

No provider I/O, classifier, historical lookup, or second identity authority.
The caller holds the workspace gate in its per-message transaction.
"""
from rest_framework.exceptions import NotFound, ValidationError

from .models import AccountMailboxBinding, EmailAccount, MailboxPrincipal
from .retention import retain_observation


def mailbox_for_account(account):
    """Resolve only the verified binding; absence is explicitly unresolved.

    Also used before fetching, then revalidated under the workspace gate. A
    binding established during a fetch cannot authenticate that earlier fetch.
    """
    if not EmailAccount.objects.filter(
        pk=account.pk, workspace_id=account.workspace_id, provider="gmail"
    ).exists():
        raise NotFound()
    binding = AccountMailboxBinding.objects.select_related("mailbox").filter(account_id=account.pk).first()
    if binding is None:
        return None
    mailbox = binding.mailbox
    if mailbox.workspace_id != account.workspace_id or mailbox.provider != "gmail":
        raise NotFound()
    principal = MailboxPrincipal.objects.filter(mailbox=mailbox).first()
    if principal is None:
        return None
    if (principal.workspace_id != account.workspace_id or principal.provider != "gmail"
            or principal.namespace != "google_oidc_sub"):
        raise ValidationError("Invalid Gmail mailbox binding.")
    return mailbox.pk


def retain_gmail_message(account, message, reason, mailbox_id):
    current_mailbox = mailbox_for_account(account)
    if current_mailbox != mailbox_id:
        raise ValidationError("Gmail mailbox binding changed during sync; retry the fetch.")
    internal = message.provider_internal_at
    unknown = {"precision": "unknown", "value": None, "source": "unknown"}

    def body(value):
        return {"value": value, "completeness": "unavailable" if value is None else "complete"}

    return retain_observation(
        actor=account.workspace.owner, workspace=account.workspace,
        key="gmail-fetch:" + message.observation_key,
        observation={
            "reason": reason, "observed_at": message.observed_at.isoformat(),
            "mailbox_id": mailbox_id,
            "source": {"provider": "gmail", "kind": "gmail_message_id",
                       "value": message.provider_message_id, "folder": "", "stability": "v1"},
            "content": {
                "subject": message.subject, "addresses": message.addresses,
                "headers": [list(header) for header in message.selected_headers],
                "text": body(message.text_body), "html": body(message.html_body),
                "header_sent": message.header_sent or unknown,
                "provider_received": {"precision": "instant", "value": internal.isoformat(),
                                      "source": "gmail_internal_date"} if internal else unknown,
                "provenance": {"method": "gmail_raw_mime", "version": "1"},
                "conversation_id": message.provider_thread_id or "",
            },
        },
    )
