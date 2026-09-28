"""Additive item schema on a disposable populated checkpoint database."""
import tempfile
from django.conf import settings
from django.db import connections, migrations
import uuid
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class RetainedItemMigrationTests(TransactionTestCase):
    def test_populated_checkpoint_preserved_without_fabrication(self):
        with tempfile.TemporaryDirectory() as temp:
            alias = "posting_item_fixture"
            config = dict(connections["default"].settings_dict)
            config.update(NAME=temp + "/fixture.sqlite3", ENGINE="django.db.backends.sqlite3", OPTIONS={})
            original = self.databases
            type(self).databases = original | {alias}
            connections.databases[alias] = config
            db = connections[alias]
            try:
                executor = MigrationExecutor(db)
                others = [node for node in executor.loader.graph.leaf_nodes() if node[0] != "postings"]
                baseline = others + [("postings", "0004_retained_posting_extraction_provenance")]
                target = others + [("postings", "0005_retained_posting_items")]
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
                mailbox = create("email_sync", "MailboxLineage", workspace_id=ws.pk, provider="gmail",
                                 evidence={"method": "fixture", "reference": "preserve"})
                message = create("email_sync", "RetainedMessage", workspace_id=ws.pk, mailbox_id=mailbox.pk,
                                 provider="gmail", locator_kind="gmail_message_id", locator_value="native",
                                 stability="v1", content={"historical": "preserved"}, content_digest="preserve")
                key = create("email_sync", "RetentionKey", workspace_id=ws.pk, key="original", initial_digest="preserve")
                observation = create("email_sync", "RetainedObservation", workspace_id=ws.pk, key_id=key.pk,
                    message_id=message.pk, mailbox_id=mailbox.pk, digest="preserve", payload={"fixture": True},
                    state="retained", observed_at=stamp)
                review = create("applications", "RetainedApplicationReview", workspace_id=ws.pk,
                    retained_message_id=message.pk, originating_observation_id=observation.pk,
                    initial_classification="match")
                create("applications", "RetainedApplicationReviewCandidate", review_id=review.pk,
                       application_id=app.pk, application_portable_id=app.portable_id)
                create("applications", "RetainedApplicationReviewDisposition", review_id=review.pk,
                       dismissed_at=stamp, revision=2)
                create("applications", "ApplicationMessage", workspace_id=ws.pk, application_id=app.pk,
                       retained_message_id=message.pk)
                for n in range(3):
                    extraction = create("postings", "RetainedPostingExtraction", retained_message_id=message.pk,
                        operation_id=uuid.uuid4(), extractor_method="job_alert_rules", extractor_version="1",
                        snapshot_version=1, input_spec={"historical": "unchanged"}, payload_digest="a" * 64,
                        extracted_at=stamp)
                    for position in range(n):
                        create("postings", "RetainedPostingExtractionOutput", extraction_id=extraction.pk,
                            portable_id=uuid.uuid4(), position=position, fields={"title": "Same"})
                def snapshot(table):
                    with db.cursor() as cursor:
                        cursor.execute(f"SELECT * FROM {db.ops.quote_name(table)} ORDER BY 1")
                        return [col[0] for col in cursor.description], cursor.fetchall()
                tables = set(db.introspection.table_names()) - {"django_migrations"}
                before = {table: snapshot(table) for table in tables}
                executor = MigrationExecutor(db)
                migration = executor.loader.get_migration("postings", "0005_retained_posting_items")
                self.assertEqual(migration.dependencies, [("postings", "0004_retained_posting_extraction_provenance"),
                                                          migrations.swappable_dependency(settings.AUTH_USER_MODEL)])
                self.assertEqual([type(op).__name__ for op in migration.operations],
                                 ["CreateModel", "CreateModel", "AddConstraint", "AddConstraint", "AddConstraint", "AddConstraint"])
                self.assertEqual([m.name for m, reverse in executor.migration_plan(target)],
                                 ["0005_retained_posting_items"])
                executor.migrate(target)
                new_tables = {"postings_retainedpostingitem", "postings_retainedpostingitemassociation"}
                def check():
                    self.assertEqual(set(db.introspection.table_names()) - {"django_migrations"}, tables | new_tables)
                    for table in tables:
                        self.assertEqual(before[table], snapshot(table), table)
                    for table in new_tables:
                        self.assertEqual(snapshot(table)[1], [])
                check()
                MigrationExecutor(db).migrate(target)
                check()
            finally:
                db.close()
                del connections[alias]
                del connections.databases[alias]
                type(self).databases = original
