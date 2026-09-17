"""Only migrate forward from the populated checkpoint on the isolated test DB.

Never reverse/replay documents.0002; rollback of conversion removal is deliberately
unsupported because a single old pointer cannot represent repeated conversions.
"""
import importlib
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class IdentityMigrationTests(TransactionTestCase):
    def test_populated_checkpoint_preserves_pks_foreign_keys_and_known_conversion(self):
        # The test runner starts at leaf state. Build a separate temporary SQLite
        # database so no destructive backwards migration or real tracker is used.
        import tempfile
        from django.db import connections
        with tempfile.TemporaryDirectory() as temp:
            alias = "identity_migration_fixture"
            config = dict(connections["default"].settings_dict)
            config["NAME"] = temp + "/migration.sqlite3"
            config["ENGINE"] = "django.db.backends.sqlite3"
            config["OPTIONS"] = {}
            original_databases = self.databases
            type(self).databases = self.databases | {alias}
            connections.databases[alias] = config
            db = connections[alias]
            try:
                executor = MigrationExecutor(db)
                leaves = executor.loader.graph.leaf_nodes()
                baseline = [(app, name) for app, name in leaves if app not in {"applications", "postings", "core", "documents"}]
                baseline += [("documents", "0002_document_and_fk_refactor"), ("applications", "0001_initial"), ("postings", "0001_initial"), ("core", "0002_alter_hubsettings_role_location_default")]
                executor.migrate(baseline)
                old = executor.loader.project_state(baseline).apps
                def create(app, model, **values):
                    return old.get_model(app, model).objects.using(alias).create(**values)
                user = create("accounts", "User", username="fixture")
                ws = create("accounts", "Workspace", owner_id=user.pk, name="Fixture")
                a = create("applications", "Application", workspace_id=ws.pk, company="Same", role_label="Role", section="applications", source_relpath="one")
                b = create("applications", "Application", workspace_id=ws.pk, company="Same", role_label="Role", section="credentials", source_relpath="two")
                override = create("applications", "Override", application_id=a.pk, notes="preserve")
                from django.utils import timezone
                history = create("applications", "StatusHistory", application_id=a.pk, status="applied", changed_at=timezone.now())
                doc = create("documents", "Document", workspace_id=ws.pk, application_id=a.pk, file="fixture/no-write", filename="same.txt", ext=".txt", content_hash="hash", size=1)
                account = create("email_sync", "EmailAccount", workspace_id=ws.pk, email="fixture@example.test")
                job = create("postings", "JobPosting", workspace_id=ws.pk, account_id=account.pk, applied_application_id=a.pk, dedupe_key="known")
                create("postings", "JobPosting", workspace_id=ws.pk, account_id=account.pk, dedupe_key="unknown")
                executor = MigrationExecutor(db)
                executor.migrate(leaves)
                new = executor.loader.project_state(leaves).apps
                apps = new.get_model("applications", "Application").objects.using(alias)
                self.assertEqual(list(apps.order_by("pk").values_list("pk", "source_relpath")), [(a.pk, "one"), (b.pk, "two")])
                ids = list(apps.order_by("pk").values_list("portable_id", flat=True))
                self.assertEqual(len(set(ids)), 2)
                self.assertNotIn(None, ids)
                for app, model, pk in (("applications", "Override", override.pk), ("applications", "StatusHistory", history.pk), ("documents", "Document", doc.pk)):
                    self.assertEqual(new.get_model(app, model).objects.using(alias).get(pk=pk).application_id, a.pk)
                conversions = new.get_model("postings", "PostingApplicationConversion").objects.using(alias)
                c = conversions.get()
                self.assertEqual((c.posting_id, c.application_id, c.application_portable_id), (job.pk, a.pk, ids[0]))
                self.assertIsNone(c.converted_at)
                self.assertIsNone(c.request_intent_id)
                module = importlib.import_module("applications.migrations.0002_application_portable_identity")
                with db.schema_editor() as editor:
                    module.backfill_portable_ids(new, editor)
                self.assertEqual(list(apps.order_by("pk").values_list("portable_id", flat=True)), ids)
            finally:
                db.close()
                del connections[alias]
                del connections.databases[alias]
                type(self).databases = original_databases
