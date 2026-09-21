"""Upgrade a populated retained-foundation database in an isolated temp file."""
import tempfile

from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class GmailIdentityMigrationTests(TransactionTestCase):
    def test_additive_upgrade_preserves_all_old_columns_without_identity_backfill(self):
        with tempfile.TemporaryDirectory() as temp:
            alias = 'gmail_identity_fixture'
            config = dict(connections['default'].settings_dict)
            config.update(NAME=temp + '/fixture.sqlite3', ENGINE='django.db.backends.sqlite3', OPTIONS={})
            original = self.databases
            type(self).databases = original | {alias}
            connections.databases[alias] = config
            db = connections[alias]
            try:
                executor = MigrationExecutor(db)
                leaves = executor.loader.graph.leaf_nodes()
                # Preserve the pre-lineage graph's original Application schema,
                # rather than bringing future relationship storage into baseline.
                baseline = [n for n in leaves if n[0] not in {'email_sync', 'applications'}] + [
                    ('applications', '0006_deterministic_derivation'), ('email_sync', '0006_retained_email_foundation')]
                executor.migrate(baseline)
                baseline_tables = db.introspection.table_names()
                self.assertIn('email_sync_retainedmessage', baseline_tables)
                self.assertNotIn('email_sync_mailboxprincipal', baseline_tables)
                self.assertNotIn('email_sync_accountmailboxbinding', baseline_tables)
                self.assertNotIn('applications_applicationmessage', baseline_tables)
                old = executor.loader.project_state(baseline).apps
                def create(model, **values):
                    return old.get_model('email_sync', model).objects.using(alias).create(**values)
                user = old.get_model('accounts', 'User').objects.using(alias).create(username='fixture')
                ws = old.get_model('accounts', 'Workspace').objects.using(alias).create(owner_id=user.pk, name='Fixture')
                for provider in ['gmail', 'gmail', 'outlook', 'imap']:
                    account = create('EmailAccount', workspace_id=ws.pk, provider=provider, email='same@example.test', matched_email_count=3)
                    create('GmailCredential', account_id=account.pk, access_token='encrypted-fixture', refresh_token='encrypted-fixture', scopes='https://www.googleapis.com/auth/gmail.readonly')
                    create('Discovery', account_id=account.pk, message_id='<legacy>', subject='Preserve')
                mailbox = create('MailboxLineage', workspace_id=ws.pk, provider='gmail', evidence={'method': 'fixture', 'reference': 'unverified'})
                message = create('RetainedMessage', workspace_id=ws.pk, mailbox_id=mailbox.pk, provider='gmail',
                                 locator_kind='gmail_message_id', locator_value='fixture-id', stability='v1',
                                 content={'fixture': True}, content_digest='fixture')
                key = create('RetentionKey', workspace_id=ws.pk, key='fixture', initial_digest='fixture')
                create('RetainedObservation', workspace_id=ws.pk, key_id=key.pk, mailbox_id=mailbox.pk, message_id=message.pk,
                       digest='fixture', payload={'fixture': True}, state='retained', observed_at=timezone.now())
                tables = [t for t in db.introspection.table_names() if t != 'django_migrations']
                def snapshot(table):
                    with db.cursor() as cursor:
                        cursor.execute(f'SELECT * FROM {db.ops.quote_name(table)} ORDER BY 1')
                        return cursor.description, cursor.fetchall()
                before = {table: snapshot(table) for table in tables}
                executor = MigrationExecutor(db)
                migration = executor.loader.get_migration('email_sync', '0007_gmail_mailbox_identity')
                self.assertEqual([type(op).__name__ for op in migration.operations], ['CreateModel', 'CreateModel'])
                executor.migrate(leaves)
                new = executor.loader.project_state(leaves).apps
                for table in tables:
                    self.assertEqual(before[table], snapshot(table), table)
                for model in ['MailboxPrincipal', 'AccountMailboxBinding']:
                    self.assertEqual(new.get_model('email_sync', model).objects.using(alias).count(), 0)
                # Forward replay is also a no-op; no backwards migration/data loss.
                MigrationExecutor(db).migrate(leaves)
                for table in tables:
                    self.assertEqual(before[table], snapshot(table), table)
            finally:
                db.close()
                del connections[alias]
                del connections.databases[alias]
                type(self).databases = original
