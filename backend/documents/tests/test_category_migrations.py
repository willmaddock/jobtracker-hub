"""Forward-only populated checkpoint upgrade in a separate temporary database."""
import importlib
import tempfile
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class CategoryMigrationTests(TransactionTestCase):
    def test_populated_backfill_preserves_identity_children_and_ambiguous_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            alias = 'category_migration_fixture'
            config = dict(connections['default'].settings_dict)
            config.update(NAME=temp+'/migration.sqlite3', ENGINE='django.db.backends.sqlite3', OPTIONS={})
            original_databases = self.databases
            type(self).databases = self.databases | {alias}
            connections.databases[alias] = config
            db = connections[alias]
            try:
                executor = MigrationExecutor(db)
                leaves = executor.loader.graph.leaf_nodes()
                baseline = [(app, name) for app, name in leaves if app not in {'applications', 'documents', 'core'}]
                baseline += [('applications', '0003_allow_repeated_attempts'), ('documents', '0002_document_and_fk_refactor'), ('core', '0003_applicationrequestintent')]
                executor.migrate(baseline)
                old = executor.loader.project_state(baseline).apps
                def create(app, model, **values):
                    return old.get_model(app, model).objects.using(alias).create(**values)
                user = create('accounts', 'User', username='fixture')
                ws = create('accounts', 'Workspace', owner_id=user.pk, name='A')
                other = create('accounts', 'Workspace', owner_id=user.pk, name='B')
                rows = [create('applications', 'Application', workspace_id=workspace.pk, section=section,
                               company='Same', role_label='Role', source_relpath=f'preserved/{i}')
                        for i, (workspace, section) in enumerate([(ws, 'applications'), (ws, 'credentials'),
                            (ws, 'credentials'), (ws, 'custom-slug'), (ws, 'another-custom'), (other, 'credentials')])]
                ov = create('applications', 'Override', application_id=rows[1].pk, notes='Keep', archived=True)
                history = create('applications', 'StatusHistory', application_id=rows[1].pk, status='applied', changed_at=timezone.now())
                doc = create('documents', 'Document', workspace_id=ws.pk, application_id=rows[1].pk, file='fixture/no-write', filename='file.txt', size=1, ext='.txt', content_hash='hash')
                account = create('email_sync', 'EmailAccount', workspace_id=ws.pk, email='fixture@example.test')
                job = create('postings', 'JobPosting', workspace_id=ws.pk, account_id=account.pk, dedupe_key='fixture')
                conversion = create('postings', 'PostingApplicationConversion', workspace_id=ws.pk, posting_id=job.pk,
                                    application_id=rows[1].pk, application_portable_id=rows[1].portable_id)
                matching = create('documents', 'FolderOverride', workspace_id=ws.pk, folder='credentials', section='credentials', archived=True)
                # Preserve the exact key's observed adapter flag, not a folder claim.
                conflict = create('documents', 'FolderOverride', workspace_id=ws.pk, folder='custom-slug', section='network', archived=True)
                create('documents', 'FolderOverride', workspace_id=ws.pk, folder='physical/ambiguous', section='credentials', archived=True)
                create('documents', 'FolderOverride', workspace_id=ws.pk, folder='unused', section='misc', archived=True)
                before_apps = list(old.get_model('applications', 'Application').objects.using(alias).order_by('pk').values())
                before_folders = list(old.get_model('documents', 'FolderOverride').objects.using(alias).order_by('pk').values())
                preserved = [('applications', 'Override', ov.pk), ('applications', 'StatusHistory', history.pk),
                             ('documents', 'Document', doc.pk), ('postings', 'PostingApplicationConversion', conversion.pk)]
                before_children = [old.get_model(a, m).objects.using(alias).values().get(pk=pk) for a, m, pk in preserved]
                executor = MigrationExecutor(db)
                executor.migrate(leaves)
                new = executor.loader.project_state(leaves).apps
                apps = new.get_model('applications', 'Application').objects.using(alias)
                after_apps = list(apps.order_by('pk').values())
                self.assertEqual([row.pop('category_revision') for row in after_apps], [0, 1, 1, 1, 1, 1])
                self.assertEqual(after_apps, before_apps)
                self.assertEqual([new.get_model(a, m).objects.using(alias).values().get(pk=pk) for a, m, pk in preserved], before_children)
                self.assertEqual(list(new.get_model('documents', 'FolderOverride').objects.using(alias).order_by('pk').values()), before_folders)
                cats = new.get_model('documents', 'Category').objects.using(alias)
                members = new.get_model('documents', 'CategoryMembership').objects.using(alias)
                self.assertEqual(cats.count(), 4)
                self.assertEqual(members.count(), 5)
                self.assertFalse(members.filter(application_id=rows[0].pk).exists())
                first = cats.get(pk=members.get(application_id=rows[1].pk).category_id)
                self.assertEqual(members.get(application_id=rows[2].pk).category_id, first.pk)
                self.assertEqual(first.provenance, {'kind': 'synthetic_section_group', 'source_section': 'credentials', 'archive_adapter_override_id': matching.pk})
                self.assertTrue(first.archived)
                custom = cats.get(pk=members.get(application_id=rows[3].pk).category_id)
                self.assertEqual(custom.section, 'misc')
                self.assertEqual(custom.provenance['source_section'], 'custom-slug')
                self.assertEqual(custom.provenance['archive_adapter_override_id'], conflict.pk)
                self.assertTrue(custom.archived)
                self.assertNotEqual(custom.pk, members.get(application_id=rows[4].pk).category_id)
                self.assertFalse(cats.get(workspace_id=other.pk).archived)
                self.assertEqual(len(set(cats.values_list('portable_id', flat=True))), 4)
                before_categories = list(cats.order_by('pk').values())
                before_members = list(members.order_by('application_id').values())
                module = importlib.import_module('documents.migrations.0004_backfill_synthetic_categories')
                with db.schema_editor() as editor:
                    module.backfill(new, editor)
                self.assertEqual(list(cats.order_by('pk').values()), before_categories)
                self.assertEqual(list(members.order_by('application_id').values()), before_members)
            finally:
                db.close()
                del connections[alias]
                del connections.databases[alias]
                type(self).databases = original_databases
