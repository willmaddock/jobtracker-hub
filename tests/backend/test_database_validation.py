"""Safety refusals are tested without provisioning or contacting a database."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import run_database_validation as harness


class HarnessSafetyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='jth-pg-', dir='/private/tmp')
        self.root = Path(self.directory.name)
        for child in ('data', 'socket'):
            (self.root / child).mkdir(mode=0o700)
        (self.root / 'data' / 'PG_VERSION').write_text('17\n')
        token = self.root.name.removeprefix('jth-pg-')
        self.run = dict(root=str(self.root), data=str(self.root/'data'), socket=str(self.root/'socket'),
            role='jth_'+token, database='test_jth_'+token, system_id='12345', bin='/unused/bin')
        self.manifest = self.root/'manifest.json'
        self.manifest.write_text(json.dumps(self.run)); self.manifest.chmod(0o600)

    def tearDown(self):
        self.directory.cleanup()

    def write(self, **changes):
        self.manifest.write_text(json.dumps(self.run | changes))

    def test_owned_manifest(self):
        self.assertEqual(harness.load_manifest(self.manifest), self.run)

    def test_missing_manifest(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            harness.load_manifest()

    def test_public_manifest_and_directory(self):
        for path in (self.manifest, self.root/'socket', self.root):
            path.chmod(0o755)
            with self.assertRaises(ValueError): harness.load_manifest(self.manifest)
            path.chmod(0o600 if path == self.manifest else 0o700)

    def test_symlink_socket(self):
        socket = self.root/'socket'; socket.rmdir(); socket.symlink_to(self.root/'data')
        with self.assertRaises(ValueError): harness.load_manifest(self.manifest)
        socket.unlink()

    def test_foreign_children_and_names(self):
        for changes in ({'data':'/private/tmp'}, {'socket':'/tmp'}, {'database':'production'},
                        {'role':'postgres'}, {'system_id':'bad'}, {'root':'/private/tmp'}):
            self.write(**changes)
            with self.assertRaises(ValueError): harness.load_manifest(self.manifest)

    def test_wrong_major(self):
        (self.root/'data'/'PG_VERSION').write_text('18')
        with self.assertRaises(ValueError): harness.load_manifest(self.manifest)

    def actual(self, **changes):
        return json.dumps(dict(data=self.run['data'], socket=self.run['socket'], listen='',
            role=self.run['role'], version='170011', system_id='12345') | changes)

    def test_live_identity_mismatches(self):
        for changes in ({'data':'/real'}, {'socket':'/tmp'}, {'listen':'localhost'},
                        {'role':'postgres'}, {'version':'180000'}, {'system_id':'54321'}):
            with patch.object(harness, 'sql', return_value=self.actual(**changes)), self.assertRaises(ValueError):
                harness.verify_server(self.run)

    def test_existing_database_refused(self):
        with patch.object(harness, 'verify_server'), patch.object(harness, 'sql', return_value='1'), self.assertRaises(ValueError):
            harness.assert_fresh_database(self.run)

    def test_cleanup_refuses_wrong_server_before_stop_or_delete(self):
        with patch.object(harness, 'sql', return_value=self.actual(system_id='54321')), \
             patch.object(harness.subprocess, 'run') as stop, patch.object(harness.shutil, 'rmtree') as delete:
            with self.assertRaises(ValueError): harness.cleanup(self.run)
            stop.assert_not_called(); delete.assert_not_called()

    def test_cleanup_refuses_changed_stopped_identity(self):
        with patch.object(harness, 'verify_server'), patch.object(harness.subprocess, 'run'), \
             patch.object(harness.subprocess, 'check_output', return_value='Database system identifier: 54321'), \
             patch.object(harness.shutil, 'rmtree') as delete:
            with self.assertRaises(ValueError): harness.cleanup(self.run)
            delete.assert_not_called()

    def creation_fixture(self, *, collide):
        from contextlib import nullcontext
        from types import SimpleNamespace
        from django.db import DatabaseError
        from unittest.mock import MagicMock
        connection = MagicMock()
        connection.settings_dict = {"TEST": {"NAME": self.run['database'], "CHARSET": None,
                                             "COLLATION": None, "TEMPLATE": None}}
        connection.ops.quote_name.side_effect = lambda name: '"' + name + '"'
        creation = harness.creation_class()(connection)
        state = {'exists': False, 'statements': []}
        cursor = MagicMock()
        def execute(statement):
            state['statements'].append(statement)
            if statement.startswith('CREATE DATABASE'):
                if collide:
                    # Another creator wins after the completed absence preflight.
                    state['exists'] = True
                    cause = RuntimeError('duplicate database')
                    cause.sqlstate = '42P04'
                    raise DatabaseError('database already exists') from cause
                state['exists'] = True
            elif statement.startswith('DROP DATABASE'):
                state['exists'] = False
        cursor.execute.side_effect = execute
        creation._nodb_cursor = lambda: nullcontext(cursor)
        return creation, state

    def test_creation_collision_after_absent_preflight_never_drops(self):
        with patch.object(harness, 'verify_server'), patch.object(harness, 'sql', return_value='0'):
            harness.assert_fresh_database(self.run)
        creation, state = self.creation_fixture(collide=True)
        # Exercise Django's public entry with noninteractive autoclobber requested.
        with self.assertRaisesRegex(harness.ValidationDatabaseCreationFailure, 'safety failure.*42P04'):
            creation.create_test_db(verbosity=0, autoclobber=True, keepdb=False)
        self.assertTrue(state['exists'], 'Colliding database must survive')
        self.assertEqual(len(state['statements']), 1, 'No retry is permitted')
        self.assertTrue(state['statements'][0].startswith('CREATE DATABASE'))
        self.assertFalse(any('DROP DATABASE' in sql for sql in state['statements']))

    def test_fresh_creation_without_autoclobber(self):
        creation, state = self.creation_fixture(collide=False)
        self.assertEqual(creation._create_test_db(verbosity=0, autoclobber=True), self.run['database'])
        self.assertTrue(state['exists'])
        self.assertEqual(len(state['statements']), 1)

    def test_routing_environment_cleared(self):
        with patch.dict(os.environ, {'PGHOST':'real', 'PGSERVICE':'real', 'PGDATABASE':'real', 'DATABASE_URL':'real'}):
            env = harness.clean_environment()
        self.assertFalse(any(key.startswith('PG') for key in env))
        self.assertNotIn('DATABASE_URL', env)

    def test_keepdb_and_clones_refused(self):
        import sys
        sys.path.insert(0, str(harness.ROOT/'backend'))
        with patch.dict(os.environ, {'DJANGO_SETTINGS_MODULE':'config.settings.test_sqlite'}):
            cls = harness.runner_class()
            for options in ({'keepdb':True}, {'parallel':2}):
                with self.assertRaises(ValueError): cls(**options)


if __name__ == '__main__':
    unittest.main()
