"""Populated forward-only migration, never a real tracker database."""
import tempfile
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class RetentionMigrationTests(TransactionTestCase):
    def test_checkpoint_graph_preserved_and_no_historical_email_promoted(self):
        with tempfile.TemporaryDirectory() as temp:
            alias = "retained_fixture"
            config = dict(connections["default"].settings_dict)
            config.update(NAME=temp + "/fixture.sqlite3", ENGINE="django.db.backends.sqlite3", OPTIONS={})
            original = self.databases
            type(self).databases = original | {alias}
            connections.databases[alias] = config
            db = connections[alias]
            try:
                executor = MigrationExecutor(db)
                leaves = executor.loader.graph.leaf_nodes()
                baseline = [node for node in leaves if node[0] != "email_sync"] + [("email_sync", "0005_imapcredential")]
                executor.migrate(baseline)
                old = executor.loader.project_state(baseline).apps
                def create(app, model, **values):
                    return old.get_model(app, model).objects.using(alias).create(**values)
                user = create("accounts", "User", username="migration")
                stamp = timezone.now()
                for n in range(3):
                    ws = create("accounts", "Workspace", owner_id=user.pk, name=str(n))
                    app = create("applications", "Application", workspace_id=ws.pk, company="Same", section="applications",
                        status="applied", first_activity=stamp, last_activity=stamp, derivation_state="complete",
                        derivation_fingerprint="old", derived_at=stamp,
                        source_relpath="legacy/path", trashed_at=stamp if n == 1 else None, lifecycle_revision=4)
                    create("applications", "Override", application_id=app.pk, manual_status="applied", notes="retain", archived=True)
                    create("applications", "StatusHistory", application_id=app.pk, status="applied", changed_at=stamp)
                    doc = create("documents", "Document", workspace_id=ws.pk, application_id=app.pk, file="retained/original.pdf",
                        filename="original.pdf", ext=".pdf", size=20, content_hash=str(n), doc_type="application_confirmation",
                        trashed_at=stamp if n == 2 else None, lifecycle_revision=2)
                    create("documents", "DocumentOverride", document_id=doc.pk, doc_type_override="application_confirmation")
                    create("documents", "DocumentExtraction", workspace_id=ws.pk, document_id=doc.pk,
                        content_hash=str(n), extractor_version="4", extracted_json={"retained": True}, extracted_at=stamp)
                    cat = create("documents", "Category", workspace_id=ws.pk, name="Shelf", section="misc", archived=True)
                    create("documents", "CategoryMembership", application_id=app.pk, category_id=cat.pk)
                    create("documents", "FolderOverride", workspace_id=ws.pk, folder="legacy", section="misc")
                    intent = create("core", "ApplicationRequestIntent", actor_id=user.pk, workspace_id=ws.pk, key=str(n),
                        digest="retained", kind="manual", application_id=app.pk, result_portable_id=app.portable_id, completed=True)
                    account = create("email_sync", "EmailAccount", workspace_id=ws.pk, email="same@example.test", provider=["gmail", "outlook", "imap"][n])
                    create("email_sync", "GmailCredential", account_id=account.pk, access_token="fixture-ciphertext", refresh_token="fixture-ciphertext")
                    create("email_sync", "OutlookCredential", account_id=account.pk, access_token="fixture-ciphertext", refresh_token="fixture-ciphertext")
                    create("email_sync", "IMAPCredential", account_id=account.pk, host="fixture", username="fixture", password="fixture-ciphertext")
                    create("email_sync", "AccountMatch", account_id=account.pk, application_id=app.pk, message_id="<weak>", subject="Old metadata", received_at=stamp)
                    discovery = create("email_sync", "Discovery", account_id=account.pk, message_id="<weak>", status="dismissed", received_at=stamp)
                    discovery.candidate_applications.add(app)
                    create("email_sync", "ThreadIdentifier", application_id=app.pk, message_id="<weak>")
                    create("email_sync", "JobPostingSender", workspace_id=ws.pk, sender="fixture")
                    posting = create("postings", "JobPosting", workspace_id=ws.pk, account_id=account.pk, dedupe_key=str(n))
                    create("postings", "PostingApplicationConversion", workspace_id=ws.pk, posting_id=posting.pk,
                        application_id=app.pk, application_portable_id=app.portable_id, request_intent_id=intent.pk)
                # Compare every column in every pre-existing table, including M2M,
                # stored credentials, file references, derivation and lifecycle state.
                tables = [table for table in db.introspection.table_names() if table != "django_migrations"]
                def snapshot(table):
                    with db.cursor() as cursor:
                        cursor.execute(f'SELECT * FROM {db.ops.quote_name(table)} ORDER BY 1')
                        return cursor.description, cursor.fetchall()
                before = {table: snapshot(table) for table in tables}
                executor = MigrationExecutor(db)
                executor.migrate(leaves)
                new = executor.loader.project_state(leaves).apps
                for table in tables:
                    self.assertEqual(before[table], snapshot(table), table)
                for model in ["MailboxLineage", "RetainedMessage", "RetentionKey", "RetainedObservation"]:
                    self.assertEqual(new.get_model("email_sync", model).objects.using(alias).count(), 0)
                # An already applied forward plan is a no-op even with new retained
                # references; no backwards schema migration is used for cleanup.
                mailbox = new.get_model("email_sync", "MailboxLineage").objects.using(alias).create(
                    workspace_id=ws.pk, provider="gmail", evidence={"method": "fixture", "reference": "explicit"})
                retained = new.get_model("email_sync", "RetainedMessage").objects.using(alias).create(
                    workspace_id=ws.pk, mailbox_id=mailbox.pk, provider="gmail", locator_kind="gmail_message_id",
                    locator_value="known", stability="v1", content={"fixture": True}, content_digest="fixture")
                MigrationExecutor(db).migrate(leaves)
                self.assertEqual(new.get_model("email_sync", "RetainedMessage").objects.using(alias).get(pk=retained.pk).mailbox_id, mailbox.pk)
            finally:
                db.close()
                del connections[alias]
                del connections.databases[alias]
                type(self).databases = original
