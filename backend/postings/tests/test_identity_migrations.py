"""Forward-only populated posting identity upgrade on a disposable database."""
import importlib
import tempfile
import uuid

from django.db import IntegrityError, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class PostingIdentityMigrationTests(TransactionTestCase):
    def test_populated_upgrade_preserves_every_old_field_and_relationship(self):
        with tempfile.TemporaryDirectory() as temp:
            alias = "posting_identity_fixture"
            config = dict(connections["default"].settings_dict)
            config.update(NAME=temp + "/fixture.sqlite3", ENGINE="django.db.backends.sqlite3", OPTIONS={})
            original = self.databases
            type(self).databases = original | {alias}
            connections.databases[alias] = config
            db = connections[alias]
            try:
                executor = MigrationExecutor(db)
                others = [node for node in executor.loader.graph.leaf_nodes() if node[0] != "postings"]
                baseline = others + [("postings", "0002_posting_application_conversions")]
                target = others + [("postings", "0003_jobposting_portable_identity")]
                executor.migrate(baseline)
                old = executor.loader.project_state(baseline).apps
                def create(app, model, **values):
                    return old.get_model(app, model).objects.using(alias).create(**values)
                user = create("accounts", "User", username="fixture")
                stamp = timezone.now()
                for n in range(2):
                    ws = create("accounts", "Workspace", owner_id=user.pk, name=str(n))
                    for k in range(2):
                        account = create("email_sync", "EmailAccount", workspace_id=ws.pk,
                                         email=f"fixture{k}@example.test", provider="gmail")
                        app = create("applications", "Application", workspace_id=ws.pk,
                                     company="Same", role_label="Same", section="applications")
                        intent = create("core", "ApplicationRequestIntent", workspace_id=ws.pk,
                            actor_id=user.pk, key=f"intent-{k}", digest="preserve", kind="posting",
                            completed=True, application_id=app.pk, result_portable_id=app.portable_id)
                        for j in range(2):
                            job = create("postings", "JobPosting", workspace_id=ws.pk, account_id=account.pk,
                                message_id="same", dedupe_key=f"{n}-{k}-{j}", company="Same", title="Same",
                                source="fixture", sender="fixture@example.test", email_subject="Preserve",
                                location="Remote", salary="$100", employment_type="Full time", received_at=stamp,
                                posting_url="https://example.test/job" if j else None,
                                status="dismissed" if j else "new", saved=bool(j))
                            create("postings", "PostingApplicationConversion", workspace_id=ws.pk,
                                posting_id=job.pk, application_id=app.pk if not j else None,
                                application_portable_id=app.portable_id,
                                request_intent_id=intent.pk if not j else None,
                                converted_at=stamp if not j else None)
                        create("postings", "PostingApplicationConversion", workspace_id=ws.pk,
                               posting_id=None, application_id=None, application_portable_id=uuid.uuid4())
                tables = [t for t in db.introspection.table_names() if t != "django_migrations"]
                def snapshot(table, columns=None):
                    with db.cursor() as cursor:
                        selection = ", ".join(db.ops.quote_name(c) for c in columns) if columns else "*"
                        cursor.execute(f"SELECT {selection} FROM {db.ops.quote_name(table)} ORDER BY 1")
                        return [c[0] for c in cursor.description], cursor.fetchall()
                before = {t: snapshot(t) for t in tables}
                posting_table = "postings_jobposting"
                self.assertNotIn("portable_id", before[posting_table][0])
                executor = MigrationExecutor(db)
                migration = executor.loader.get_migration("postings", "0003_jobposting_portable_identity")
                self.assertEqual(migration.dependencies, [("postings", "0002_posting_application_conversions")])
                self.assertEqual([type(op).__name__ for op in migration.operations],
                                 ["AddField", "RunPython", "AlterField", "AddConstraint"])
                self.assertEqual([m.name for m, reverse in executor.migration_plan(target)],
                                 ["0003_jobposting_portable_identity"])
                executor.migrate(target)
                new = executor.loader.project_state(target).apps
                rows = new.get_model("postings", "JobPosting").objects.using(alias)
                identities = list(rows.order_by("pk").values_list("pk", "workspace_id", "portable_id"))
                self.assertEqual(len(identities), 8)
                self.assertTrue(all(isinstance(identity, uuid.UUID) for _, _, identity in identities))
                self.assertEqual(len({(ws, identity) for _, ws, identity in identities}), 8)
                def assert_preserved():
                    self.assertEqual(set(tables), set(db.introspection.table_names()) - {"django_migrations"})
                    for table, (columns, values) in before.items():
                        self.assertEqual((columns, values), snapshot(table, columns), table)
                    self.assertEqual(identities, list(rows.order_by("pk").values_list("pk", "workspace_id", "portable_id")))
                assert_preserved()
                module = importlib.import_module("postings.migrations.0003_jobposting_portable_identity")
                with db.schema_editor() as editor:
                    module.backfill_portable_ids(new, editor)
                assert_preserved()
                MigrationExecutor(db).migrate(target)
                assert_preserved()
                self.assertFalse(any("postingsource" in m._meta.model_name or "sourceitem" in m._meta.model_name
                                     for m in new.get_models()))
                first, second = identities[:2]
                with self.assertRaises(IntegrityError), transaction.atomic(using=alias):
                    rows.filter(pk=second[0]).update(portable_id=first[2])
                assert_preserved()
                # Cross-Workspace equality is explicitly allowed; roll back this probe.
                with transaction.atomic(using=alias):
                    other = next(row for row in identities if row[1] != first[1])
                    rows.filter(pk=other[0]).update(portable_id=first[2])
                    self.assertEqual(rows.get(pk=other[0]).portable_id, first[2])
                    transaction.set_rollback(True, using=alias)
                assert_preserved()
            finally:
                db.close()
                del connections[alias]
                del connections.databases[alias]
                type(self).databases = original
