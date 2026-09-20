"""Populated forward-only upgrade from 74f1e91 on disposable SQLite."""
import tempfile
from datetime import date
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class DerivationMigrationTests(TransactionTestCase):
    def test_checkpoint_preserved_without_timestamp_or_history_invention(self):
        with tempfile.TemporaryDirectory() as temp:
            alias = "derivation_fixture"
            config = dict(connections["default"].settings_dict)
            config.update(NAME=temp + "/fixture.sqlite3", ENGINE="django.db.backends.sqlite3", OPTIONS={})
            original = self.databases
            type(self).databases = original | {alias}
            connections.databases[alias] = config
            db = connections[alias]
            try:
                executor = MigrationExecutor(db)
                leaves = executor.loader.graph.leaf_nodes()
                baseline = [node for node in leaves if node[0] not in {"accounts", "applications", "documents"}]
                baseline += [("accounts", "0001_initial"), ("applications", "0005_retained_lifecycle"),
                             ("documents", "0005_retained_lifecycle")]
                executor.migrate(baseline)
                old = executor.loader.project_state(baseline).apps
                def create(app, model, **values):
                    return old.get_model(app, model).objects.using(alias).create(**values)
                user = create("accounts", "User", username="migration")
                stamp = timezone.now()
                for n in range(3):
                    ws = create("accounts", "Workspace", owner_id=user.pk, name=str(n))
                    app = create("applications", "Application", workspace_id=ws.pk, company="Same", section="applications",
                        status="applied", first_activity=stamp, last_activity=stamp,
                        source_relpath="legacy/path", trashed_at=stamp if n == 1 else None, lifecycle_revision=4)
                    create("applications", "Override", application_id=app.pk, manual_status="ghosted", notes="retain",
                        date_applied=date(2000, 1, 2) if n else None, date_applied_source="confirmation" if n == 1 else None,
                        archived=True, activity_override=date(2000, 2, 2))
                    for _ in range(2):
                        create("applications", "StatusHistory", application_id=app.pk, status="ghosted", changed_at=stamp)
                    doc = create("documents", "Document", workspace_id=ws.pk, application_id=app.pk, file="retained/original.txt",
                        filename="original.txt", ext=".txt", size=20, content_hash=str(n), doc_type="resume",
                        trashed_at=stamp if n == 2 else None, lifecycle_revision=2)
                    create("documents", "DocumentOverride", document_id=doc.pk, doc_type_override="application_confirmation")
                    create("documents", "DocumentExtraction", workspace_id=ws.pk, document_id=doc.pk,
                        content_hash=str(n), extractor_version="3", extracted_json={"retained": True}, extracted_at=stamp)
                    cat = create("documents", "Category", workspace_id=ws.pk, name="Shelf", section="misc", archived=True)
                    create("documents", "CategoryMembership", application_id=app.pk, category_id=cat.pk)
                    intent = create("core", "ApplicationRequestIntent", actor_id=user.pk, workspace_id=ws.pk, key=str(n),
                        digest="retained", kind="manual", application_id=app.pk, result_portable_id=app.portable_id, completed=True)
                    account = create("email_sync", "EmailAccount", workspace_id=ws.pk, email="fixture@example.test")
                    posting = create("postings", "JobPosting", workspace_id=ws.pk, account_id=account.pk, dedupe_key=str(n))
                    create("postings", "PostingApplicationConversion", workspace_id=ws.pk, posting_id=posting.pk,
                        application_id=app.pk, application_portable_id=app.portable_id, request_intent_id=intent.pk)
                tables = [("accounts", "Workspace"), ("applications", "Application"), ("applications", "Override"),
                    ("applications", "StatusHistory"), ("documents", "Document"), ("documents", "DocumentOverride"),
                    ("documents", "DocumentExtraction"), ("documents", "Category"), ("documents", "CategoryMembership"),
                    ("core", "ApplicationRequestIntent"), ("postings", "PostingApplicationConversion")]
                before = {table: list(old.get_model(*table).objects.using(alias).order_by("pk").values()) for table in tables}
                executor = MigrationExecutor(db)
                executor.migrate(leaves)
                new = executor.loader.project_state(leaves).apps
                for table, rows in before.items():
                    after = list(new.get_model(*table).objects.using(alias).order_by("pk").values(*rows[0].keys()))
                    self.assertEqual(after, rows, table)
                for row in new.get_model("applications", "Application").objects.using(alias).all():
                    self.assertEqual(row.derivation_state, "pending")
                    self.assertEqual(row.derivation_fingerprint, "")
                    self.assertEqual(row.activity_provenance, {})
                    self.assertIsNone(row.derived_at)
                    self.assertIsNone(row.automatic_date_applied)
                    self.assertIsNone(row.last_activity_date)
                for row in new.get_model("documents", "Document").objects.using(alias).all():
                    self.assertIsNone(row.evidence_event_at)
                    self.assertIsNone(row.evidence_event_date)
                    self.assertIsNone(row.original_upload_at)
                    self.assertIsNone(row.verified_legacy_mtime)
                    self.assertEqual(row.evidence_event_provenance, {})
                for row in new.get_model("applications", "Override").objects.using(alias).all():
                    self.assertEqual(row.date_applied_mode, "legacy_preserved" if row.date_applied else "automatic")
                self.assertEqual(set(new.get_model("accounts", "Workspace").objects.using(alias).values_list("calendar_timezone", flat=True)), {"UTC"})
            finally:
                db.close()
                del connections[alias]
                del connections.databases[alias]
                type(self).databases = original
