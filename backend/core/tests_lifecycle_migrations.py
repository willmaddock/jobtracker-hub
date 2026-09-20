"""Forward upgrade from populated Named Categories checkpoint; isolated SQLite."""
import tempfile
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class LifecycleMigrationTests(TransactionTestCase):
    def test_checkpoint_upgrade_preserves_every_existing_value(self):
        with tempfile.TemporaryDirectory() as temp:
            alias = 'lifecycle_migration_fixture'
            config = dict(connections['default'].settings_dict)
            config.update(NAME=temp+'/fixture.sqlite3', ENGINE='django.db.backends.sqlite3', OPTIONS={})
            original = self.databases
            type(self).databases = self.databases | {alias}
            connections.databases[alias] = config
            db = connections[alias]
            try:
                executor = MigrationExecutor(db)
                leaves = [node for node in executor.loader.graph.leaf_nodes()
                          if node[0] not in {"applications", "documents", "accounts"}]
                leaves += [("applications", "0005_retained_lifecycle"),
                           ("documents", "0005_retained_lifecycle"), ("accounts", "0001_initial")]
                baseline = [(app, name) for app, name in leaves if app not in {'applications', 'documents'}]
                baseline += [('applications', '0004_application_category_revision'), ('documents', '0004_backfill_synthetic_categories')]
                executor.migrate(baseline)
                old = executor.loader.project_state(baseline).apps
                def create(app, model, **values):
                    return old.get_model(app, model).objects.using(alias).create(**values)
                user = create('accounts', 'User', username='fixture')
                workspaces = [create('accounts', 'Workspace', owner_id=user.pk, name=n) for n in ('A', 'B')]
                for ws in workspaces:
                    for archived in (True, False):
                        app = create('applications', 'Application', workspace_id=ws.pk, company='Repeated', role_label='Role',
                                     section='applications', source_relpath='legacy/same', status='applied', last_activity=timezone.now())
                        cat = create('documents', 'Category', workspace_id=ws.pk, name='Named', section='misc', archived=archived,
                                     provenance={'kind': 'preserved'})
                        create('documents', 'CategoryMembership', application_id=app.pk, category_id=cat.pk)
                        create('applications', 'Override', application_id=app.pk, archived=archived, manual_status='interviewing', notes='keep')
                        create('applications', 'StatusHistory', application_id=app.pk, status='interviewing', changed_at=timezone.now())
                        doc = create('documents', 'Document', workspace_id=ws.pk, application_id=app.pk, file=f'fixture/{app.pk}',
                                     filename='original.txt', content_hash=f'hash{app.pk}', ext='.txt', size=1)
                        create('documents', 'DocumentOverride', document_id=doc.pk, doc_type_override='resume')
                        create('documents', 'DocumentExtraction', workspace_id=ws.pk, document_id=doc.pk, content_hash=doc.content_hash,
                               extractor_version='original', extracted_json={'keep': True}, extracted_at=timezone.now())
                        create('documents', 'FolderOverride', workspace_id=ws.pk, folder=f'ambiguous/{app.pk}', section='misc', archived=archived)
                        create('core', 'ApplicationRequestIntent', actor_id=user.pk, workspace_id=ws.pk, key=f'key-{app.pk}',
                               digest='fixture', kind='manual', application_id=app.pk, result_portable_id=app.portable_id, completed=True)
                tables = [('accounts', 'Workspace'), ('applications', 'Application'), ('applications', 'Override'),
                          ('applications', 'StatusHistory'), ('documents', 'Category'), ('documents', 'CategoryMembership'),
                          ('documents', 'Document'), ('documents', 'DocumentOverride'), ('documents', 'DocumentExtraction'),
                          ('documents', 'FolderOverride'), ('core', 'ApplicationRequestIntent')]
                before = {t: list(old.get_model(*t).objects.using(alias).order_by('pk').values()) for t in tables}
                executor = MigrationExecutor(db)
                executor.migrate(leaves)
                new = executor.loader.project_state(leaves).apps
                for table in tables:
                    after = list(new.get_model(*table).objects.using(alias).order_by('pk').values())
                    if table[1] in {'Application', 'Category', 'Document'}:
                        for row in after:
                            self.assertIsNone(row.pop('trashed_at'))
                            self.assertEqual(row.pop('lifecycle_revision'), 0)
                    self.assertEqual(after, before[table], table)
            finally:
                db.close()
                del connections[alias]
                del connections.databases[alias]
                type(self).databases = original
