"""Additive disposition upgrade from Application 0008; isolated populated fixtures only."""
import tempfile

from django.db import IntegrityError, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class ReviewDispositionMigrationTests(TransactionTestCase):
    def test_populated_reviews_preserved_without_disposition_backfill(self):
        with tempfile.TemporaryDirectory() as temp:
            alias = "review_disposition_fixture"
            config = dict(connections["default"].settings_dict)
            config.update(NAME=temp + "/fixture.sqlite3", ENGINE="django.db.backends.sqlite3", OPTIONS={})
            original = self.databases
            type(self).databases = original | {alias}
            connections.databases[alias] = config
            db = connections[alias]
            try:
                executor = MigrationExecutor(db)
                leaves = executor.loader.graph.leaf_nodes()
                baseline = [node for node in leaves if node[0] != "applications"] + [
                    ("applications", "0008_retained_application_review")]
                executor.migrate(baseline)
                self.assertIn("applications_applicationmessage", db.introspection.table_names())
                self.assertIn("applications_retainedapplicationreview", db.introspection.table_names())
                self.assertNotIn("applications_retainedapplicationreviewdisposition", db.introspection.table_names())
                old = executor.loader.project_state(baseline).apps

                def create(app, model, **values):
                    return old.get_model(app, model).objects.using(alias).create(**values)

                user = create("accounts", "User", username="fixture")
                stamp = timezone.now()
                for n in range(3):
                    ws = create("accounts", "Workspace", owner_id=user.pk, name=str(n))
                    account = create("email_sync", "EmailAccount", workspace_id=ws.pk, provider="gmail", email="fixture@example.test")
                    create("email_sync", "GmailCredential", account_id=account.pk, access_token="fixture-ciphertext", refresh_token="fixture-ciphertext")
                    create("email_sync", "Discovery", account_id=account.pk, message_id="posting", kind="posting",
                           status="dismissed", posting_urls=["https://example.test/job"])
                    mailbox = create("email_sync", "MailboxLineage", workspace_id=ws.pk, provider="gmail",
                                     evidence={"method": "fixture", "reference": "synthetic"})
                    create("email_sync", "MailboxPrincipal", workspace_id=ws.pk, mailbox_id=mailbox.pk,
                           provider="gmail", namespace="google_oidc_sub", value=str(n))
                    create("email_sync", "AccountMailboxBinding", account_id=account.pk, mailbox_id=mailbox.pk)
                    message = create("email_sync", "RetainedMessage", workspace_id=ws.pk, mailbox_id=mailbox.pk,
                        provider="gmail", locator_kind="gmail_message_id", locator_value="same-native", stability="v1",
                        content={"fixture": True}, content_digest="fixture", has_conflict=bool(n))
                    key = create("email_sync", "RetentionKey", workspace_id=ws.pk, key="observation", initial_digest="fixture")
                    observation = create("email_sync", "RetainedObservation", workspace_id=ws.pk, key_id=key.pk, mailbox_id=mailbox.pk,
                        message_id=message.pk, digest="fixture", payload={"fixture": True}, state="retained", observed_at=stamp)
                    unresolved = create("email_sync", "RetentionKey", workspace_id=ws.pk, key="unresolved", initial_digest="unresolved")
                    create("email_sync", "RetainedObservation", workspace_id=ws.pk, key_id=unresolved.pk,
                        digest="unresolved", payload={"fixture": True}, state="unresolved", observed_at=stamp)
                    review = create("applications", "RetainedApplicationReview", workspace_id=ws.pk,
                        retained_message_id=message.pk, originating_observation_id=observation.pk,
                        initial_classification="ambiguous")
                    for attempt in range(2):
                        application = create("applications", "Application", workspace_id=ws.pk, company="Same", role_label="Role",
                            section="applications", status="applied", first_activity=stamp, last_activity=stamp,
                            source_relpath="legacy/path", trashed_at=stamp if attempt else None, lifecycle_revision=4,
                            derivation_state="pending", derivation_fingerprint="preserve")
                        create("applications", "RetainedApplicationReviewCandidate", review_id=review.pk,
                            application_id=application.pk, application_portable_id=application.portable_id)
                        if attempt < n:
                            create("applications", "ApplicationMessage", workspace_id=ws.pk,
                                application_id=application.pk, retained_message_id=message.pk)
                        create("applications", "Override", application_id=application.pk, archived=True, notes="preserve")
                        create("applications", "StatusHistory", application_id=application.pk, status="applied", changed_at=stamp)
                        create("documents", "Document", workspace_id=ws.pk, application_id=application.pk,
                            file="fixture/original.pdf", filename="original.pdf", ext=".pdf", size=10,
                            content_hash="fixture", trashed_at=stamp if attempt else None, lifecycle_revision=2)
                        create("email_sync", "AccountMatch", account_id=account.pk, application_id=application.pk, message_id=str(attempt))
                        discovery = create("email_sync", "Discovery", account_id=account.pk, message_id=str(attempt), status="dismissed")
                        discovery.candidate_applications.add(application)
                        create("email_sync", "ThreadIdentifier", application_id=application.pk, message_id="<shared>")
                        create("postings", "JobPosting", workspace_id=ws.pk, account_id=account.pk, dedupe_key=f"{n}-{attempt}")
                tables = [table for table in db.introspection.table_names() if table != "django_migrations"]

                def snapshot(table):
                    with db.cursor() as cursor:
                        cursor.execute(f'SELECT * FROM {db.ops.quote_name(table)} ORDER BY 1')
                        return cursor.description, cursor.fetchall()

                before = {table: snapshot(table) for table in tables}
                executor = MigrationExecutor(db)
                migration = executor.loader.get_migration("applications", "0009_retained_application_review_disposition")
                self.assertEqual(migration.dependencies, [("applications", "0008_retained_application_review")])
                self.assertEqual([type(op).__name__ for op in migration.operations], ["CreateModel"])
                self.assertEqual([m.name for m, backwards in executor.migration_plan(leaves)],
                                 ["0009_retained_application_review_disposition"])
                executor.migrate(leaves)
                new = executor.loader.project_state(leaves).apps
                disposition = new.get_model("applications", "RetainedApplicationReviewDisposition")
                self.assertEqual(disposition.objects.using(alias).count(), 0)
                for table in tables:
                    self.assertEqual(before[table], snapshot(table), table)
                # A second forward run must not synthesize defaults either.
                MigrationExecutor(db).migrate(leaves)
                self.assertEqual(disposition.objects.using(alias).count(), 0)
                # DB identity is one disposition per review. These synthetic rows
                # are explicit test writes after upgrade, never migration effects.
                row = disposition.objects.using(alias).create(review_id=review.pk, dismissed_at=stamp, revision=1)
                self.assertEqual(row.pk, review.pk)
                with self.assertRaises(IntegrityError), transaction.atomic(using=alias):
                    disposition.objects.using(alias).create(review_id=review.pk, revision=0)
                recorded = list(disposition.objects.using(alias).values())
                MigrationExecutor(db).migrate(leaves)
                self.assertEqual(recorded, list(disposition.objects.using(alias).values()))
                for table in tables:
                    self.assertEqual(before[table], snapshot(table), table)
            finally:
                db.close()
                del connections[alias]
                del connections.databases[alias]
                type(self).databases = original
