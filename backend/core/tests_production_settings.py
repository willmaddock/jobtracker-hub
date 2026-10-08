"""Fresh-process configuration admission; no databases, credentials or services."""
import ast
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from django.test import SimpleTestCase

BACKEND = Path(__file__).resolve().parents[1]
KEY_NAMES = ('GMAIL_TOKEN_ENCRYPTION_KEY', 'MICROSOFT_TOKEN_ENCRYPTION_KEY', 'IMAP_TOKEN_ENCRYPTION_KEY')
DB_NAMES = ('DJANGO_DB_NAME', 'DJANGO_DB_USER', 'DJANGO_DB_PASSWORD', 'DJANGO_DB_HOST', 'DJANGO_DB_PORT')

# Read committed source literals only, never .env or stored credentials. This also
# checks that production refuses every development key without a test-only copy.
def development_defaults():
    result = {}
    for node in ast.parse((BACKEND / 'config/settings/base.py').read_text()).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in KEY_NAMES:
                result[name] = ast.literal_eval(node.value.args[1])
            elif name == 'SECRET_KEY':
                result[name] = ast.literal_eval(node.value)
    return result


# Guards are installed before settings/profile imports. The installed Python
# driver needs local libpq only; its import does not create a connection.
CHILD = r'''
import json, os, sys, socket, sqlite3, subprocess
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
# NUL cannot exist in an OS environment. Exercise that defensive boundary in a
# fresh child with a Python mapping, never by changing the parent's environment.
if os.environ.get("JTH_SETTINGS_MAPPING_OVERRIDES"):
    os.environ = dict(os.environ) | json.loads(os.environ["JTH_SETTINGS_MAPPING_OVERRIDES"])
attempts = []
dotenv_calls = []
def forbidden(name):
    def call(*args, **kwargs):
        attempts.append(name)
        raise AssertionError("External access forbidden: " + name)
    return call
try:
    with ExitStack() as guards:
        for target in ("socket.socket.connect", "socket.socket.connect_ex", "socket.create_connection", "socket.getaddrinfo", "sqlite3.connect"):
            guards.enter_context(patch(target, forbidden(target)))
        import psycopg
        guards.enter_context(patch.object(psycopg, "connect", forbidden("psycopg.connect")))
        import requests
        guards.enter_context(patch("requests.sessions.Session.request", forbidden("HTTP/provider request")))
        guards.enter_context(patch("urllib.request.urlopen", forbidden("urllib request")))
        guards.enter_context(patch("kombu.Connection.connect", forbidden("Celery broker")))
        guards.enter_context(patch("subprocess.Popen", forbidden("external subprocess")))
        from django.db.backends.base.base import BaseDatabaseWrapper
        guards.enter_context(patch.object(BaseDatabaseWrapper, "connect", forbidden("Django database connection")))
        from django.core.files.storage.base import Storage
        for name in ("open", "save", "delete", "exists", "listdir", "url"):
            guards.enter_context(patch.object(Storage, name, forbidden("storage." + name)))
        from storages.backends.s3 import S3Storage
        for name in ("_open", "_save", "delete", "exists", "listdir", "url"):
            guards.enter_context(patch.object(S3Storage, name, forbidden("S3." + name)))
        import boto3
        for name in ("client", "resource"):
            guards.enter_context(patch.object(boto3, name, forbidden("AWS." + name)))
            guards.enter_context(patch.object(boto3.session.Session, name, forbidden("AWS.Session." + name)))
        import dotenv
        original_dotenv = dotenv.load_dotenv
        def fixture_dotenv(path, *, override=False):
            dotenv_calls.append(str(path))
            if os.environ["JTH_SETTINGS_ALLOW_DOTENV"] != "yes":
                raise AssertionError("Production attempted development dotenv loading.")
            assert Path(path) == Path.cwd() / ".env"
            assert override is False
            return original_dotenv(os.environ["JTH_SETTINGS_DOTENV_FIXTURE"], override=False)
        guards.enter_context(patch.object(dotenv, "load_dotenv", fixture_dotenv))
        ACTION
        assert not attempts, attempts
        print("JTH_RESULT=" + json.dumps({"result": result, "attempts": attempts, "dotenv_calls": dotenv_calls}))
except Exception as error:
    print("JTH_RESULT=" + json.dumps({"error": type(error).__name__, "message": str(error),
        "cause": str(error.__cause__) if error.__cause__ is not None else None,
        "context": str(error.__context__) if error.__context__ is not None else None,
        "attempts": attempts, "dotenv_calls": dotenv_calls}))
    sys.exit(7)
'''

SUMMARY = '''
from django.conf import settings
result = {"profile": settings.SETTINGS_MODULE, "engine": settings.DATABASES["default"]["ENGINE"],
    "db_name": str(settings.DATABASES["default"]["NAME"]), "port": settings.DATABASES["default"].get("PORT"),
    "password_preserved": settings.DATABASES["default"].get("PASSWORD") == os.environ.get("DJANGO_DB_PASSWORD"),
    "secret_preserved": settings.SECRET_KEY == os.environ.get("DJANGO_SECRET_KEY"),
    "provider_keys_preserved": all(getattr(settings,n) == os.environ.get(n) for n in KEY_NAMES),
    "debug": settings.DEBUG, "hosts": settings.ALLOWED_HOSTS, "csrf_origins": settings.CSRF_TRUSTED_ORIGINS,
    "security": {n:getattr(settings,n) for n in SECURITY_NAMES},
    "media": str(settings.MEDIA_ROOT), "test_secret": settings.SECRET_KEY == "isolated-database-validation-only",
    "google_client": settings.GOOGLE_OAUTH_CLIENT_ID, "fallbacks": settings.SECRET_KEY_FALLBACKS}
'''.replace('KEY_NAMES', repr(KEY_NAMES)).replace('SECURITY_NAMES', repr((
    'SESSION_COOKIE_SECURE', 'CSRF_COOKIE_SECURE', 'SESSION_COOKIE_HTTPONLY',
    'SESSION_COOKIE_SAMESITE', 'CSRF_COOKIE_SAMESITE', 'SECURE_SSL_REDIRECT',
    'SECURE_PROXY_SSL_HEADER', 'USE_X_FORWARDED_HOST', 'USE_X_FORWARDED_PORT', 'SECURE_HSTS_SECONDS')))


class ProductionSettingsTests(SimpleTestCase):
    databases = set()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='jth-settings-')
        self.addCleanup(self.directory.cleanup)
        self.fixture = Path(self.directory.name) / 'development.env'
        self.fixture.write_text('GOOGLE_OAUTH_CLIENT_ID=fixture-dotenv-client\nDJANGO_SECRET_KEY=dotenv-must-not-admit-production\n')
        self.valid = {
            'DJANGO_SETTINGS_MODULE': 'config.settings.prod',
            'DJANGO_DB_NAME': 'synthetic_database', 'DJANGO_DB_USER': 'synthetic_role',
            'DJANGO_DB_PASSWORD': ' opaque-PASSWORD-CANARY-+/=@ ',
            'DJANGO_DB_HOST': 'database.example.test', 'DJANGO_DB_PORT': '5432',
            'DJANGO_SECRET_KEY': 'SECRET-CANARY-production-admission-fixture-only-0123456789-abcdef',
            'DJANGO_ALLOWED_HOSTS': ' Example.TEST ,127.0.0.1,[2001:db8::1],example.test ',
            **{name:base64.urlsafe_b64encode(bytes([251 + index]) * 32).decode('ascii') for index,name in enumerate(KEY_NAMES)},
        }

    def run_child(self, action=SUMMARY, *, changes=None, removed=(), dotenv=False):
        env = {'PATH': os.defpath, 'HOME': self.directory.name, 'PYTHONDONTWRITEBYTECODE': '1',
               'AWS_EC2_METADATA_DISABLED': 'true', 'AWS_ACCESS_KEY_ID': 'synthetic-access',
               'AWS_SECRET_ACCESS_KEY': 'synthetic-secret', 'AWS_STORAGE_BUCKET_NAME': 'synthetic-bucket',
               'AWS_DEFAULT_REGION': 'us-east-1', 'AWS_S3_REGION_NAME': 'us-east-1',
               'JTH_SETTINGS_ALLOW_DOTENV': 'yes' if dotenv else 'no',
               'JTH_SETTINGS_DOTENV_FIXTURE': str(self.fixture), 'PSYCOPG_IMPL': 'python'}
        # Explicit subprocess-only library setup, matching the existing isolated
        # PostgreSQL harness. No machine/native-library configuration is changed.
        libdir = os.environ.get('DYLD_LIBRARY_PATH')
        known_local = Path('/opt/homebrew/opt/postgresql@17/lib/postgresql')
        if libdir:
            env['DYLD_LIBRARY_PATH'] = libdir
        elif sys.platform == 'darwin' and (known_local / 'libpq.dylib').is_file():
            env['DYLD_LIBRARY_PATH'] = str(known_local)
        env.update(self.valid)
        env.update(changes or {})
        for name in removed:
            env.pop(name, None)
        mapping_overrides = {name:value for name,value in env.items() if '\x00' in value}
        if mapping_overrides:
            for name in mapping_overrides:
                del env[name]
            env['JTH_SETTINGS_MAPPING_OVERRIDES'] = json.dumps(mapping_overrides)
        source = CHILD.replace('        ACTION', '\n'.join('        ' + line if line else '' for line in action.splitlines()))
        completed = subprocess.run([sys.executable, '-B', '-c', source], cwd=BACKEND,
                                   env=env, capture_output=True, text=True, timeout=30)
        records = [line.removeprefix('JTH_RESULT=') for line in completed.stdout.splitlines() if line.startswith('JTH_RESULT=')]
        self.assertEqual(len(records), 1, completed.stdout + completed.stderr)
        data = json.loads(records[0])
        self.assertEqual(data['attempts'], [], data)
        for value in (env.get('DJANGO_DB_PASSWORD'), env.get('DJANGO_SECRET_KEY'), *(env.get(name) for name in KEY_NAMES)):
            if value and value.strip() and len(value) >= 12:
                self.assertNotIn(value, completed.stdout + completed.stderr)
        return completed, data

    def refusal(self, *, changes=None, removed=(), action=SUMMARY, message=None, context=None):
        completed, data = self.run_child(action, changes=changes, removed=removed)
        self.assertEqual(completed.returncode, 7, data)
        self.assertEqual(data['error'], 'ImproperlyConfigured', data)
        self.assertIsNone(data['cause'], data)
        self.assertEqual(data['context'], context, data)
        if message:
            self.assertEqual(data['message'], message)
        else:
            self.assertTrue(data['message'].startswith('Production configuration '), data)
        self.assertEqual(data['dotenv_calls'], [], data)

    def test_database_required_fields_controls_and_preservation(self):
        for name in DB_NAMES:
            for value in (None, '', '   ', 'synthetic\x00value', 'synthetic\nvalue', 'synthetic\x85value'):
                with self.subTest(name=name, value=value):
                    self.refusal(removed=(name,) if value is None else (), changes={} if value is None else {name:value})
            if name != 'DJANGO_DB_PASSWORD':
                for value in (' padded', 'padded '):
                    with self.subTest(name=name, value=value):
                        self.refusal(changes={name:value})
        completed,data = self.run_child()
        self.assertEqual(completed.returncode, 0, data)
        self.assertTrue(data['result']['password_preserved'])
        self.assertEqual(data['result']['port'], 5432)
        self.assertEqual(data['result']['engine'], 'django.db.backends.postgresql')

    def test_database_hosts_ports_and_unsupported_interfaces(self):
        for host in ('https://db.test', 'postgres://user@db/test', 'db,other', '/socket', 'user@db',
                     'db:5432', '[::1]:5432', '[::1]', '::1%zone', '256.2.3.4', 'bad..test', '*.test', 'bad_name'):
            with self.subTest(host=host): self.refusal(changes={'DJANGO_DB_HOST':host})
        for port in ('0','65536','-1','+5432','5432.0','true','５４３２','123456',' 5432','5432 '):
            with self.subTest(port=port): self.refusal(changes={'DJANGO_DB_PORT':port})
        for name in ('DATABASE_URL','DJANGO_DB_ENGINE'):
            self.refusal(changes={name:'unsupported-PASSWORD-CANARY'}, message=f'Production configuration does not support {name}.')
        for host in ('127.0.0.1', '2001:db8::1', 'Database.Example.Test'):
            with self.subTest(host=host):
                completed,data=self.run_child(changes={'DJANGO_DB_HOST':host})
                self.assertEqual(completed.returncode,0,data)

    def test_django_secret_admission_and_no_leaks(self):
        for value in (None,'','   ','short','a'*60,'django-insecure-'+'abcde'*12,
                      development_defaults()['SECRET_KEY'],self.valid['DJANGO_SECRET_KEY']+'\x00'):
            with self.subTest(value=value):
                self.refusal(removed=('DJANGO_SECRET_KEY',) if value is None else (),changes={} if value is None else {'DJANGO_SECRET_KEY':value})

    def test_provider_keys_formats_fallbacks_and_distinctness(self):
        defaults=development_defaults()
        for name in KEY_NAMES:
            for value in (None,'','   ','KEY-CANARY-invalid','é'*44,
                          base64.urlsafe_b64encode(b'x'*31).decode(), base64.b64encode(b'\xfb'*32).decode(), self.valid[name]+'=',
                          self.valid[name][:-1], self.valid[name]+'\n', *[defaults[n] for n in KEY_NAMES]):
                with self.subTest(name=name,value=value):
                    self.refusal(removed=(name,) if value is None else (), changes={} if value is None else {name:value})
        for a,b in ((KEY_NAMES[0],KEY_NAMES[1]),(KEY_NAMES[1],KEY_NAMES[2]),(KEY_NAMES[0],KEY_NAMES[2])):
            self.refusal(changes={b:self.valid[a]}, message='Production configuration requires distinct provider encryption keys.')
        # Noncanonical pad bits decode to the same bytes but must not be accepted.
        value=self.valid[KEY_NAMES[0]]
        alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
        replacement=alphabet[alphabet.index(value[-2])+1]
        self.refusal(changes={KEY_NAMES[0]:value[:-2]+replacement+'='})

    def test_allowed_hosts_and_same_origin_refusals(self):
        for value in (None,'',' ','example.test,',',example.test','a.test,,b.test','*','.example.test',
                      '*.example.test','https://example.test','example.test/path','user@example.test',
                      'example.test:443','[::1]:443','::1','[::1%zone]','256.1.2.3','[invalid]','bad..test','bad_name','a\x00.test'):
            with self.subTest(value=value):
                self.refusal(removed=('DJANGO_ALLOWED_HOSTS',) if value is None else (),changes={} if value is None else {'DJANGO_ALLOWED_HOSTS':value})
        for value in ('https://example.test',' '):
            self.refusal(changes={'DJANGO_CSRF_TRUSTED_ORIGINS':value},message='Production configuration does not support DJANGO_CSRF_TRUSTED_ORIGINS.')

    def test_valid_production_security_and_no_dotenv_or_external_access(self):
        completed,data=self.run_child()
        self.assertEqual(completed.returncode,0,data)
        result=data['result']
        self.assertFalse(result['debug'])
        self.assertEqual(result['hosts'],['example.test','127.0.0.1','[2001:db8::1]'])
        self.assertEqual(result['csrf_origins'],[])
        self.assertEqual(result['fallbacks'],[])
        self.assertTrue(result['secret_preserved'] and result['provider_keys_preserved'])
        self.assertEqual(result['security'],{
            'SESSION_COOKIE_SECURE':True,'CSRF_COOKIE_SECURE':True,'SESSION_COOKIE_HTTPONLY':True,
            'SESSION_COOKIE_SAMESITE':'Lax','CSRF_COOKIE_SAMESITE':'Lax','SECURE_SSL_REDIRECT':True,
            'SECURE_PROXY_SSL_HEADER':None,'USE_X_FORWARDED_HOST':False,'USE_X_FORWARDED_PORT':False,'SECURE_HSTS_SECONDS':0})
        self.assertEqual(data['dotenv_calls'],[])
        # The synthetic dotenv includes a secret, but cannot rescue missing process configuration.
        self.refusal(removed=('DJANGO_SECRET_KEY',))

    def test_exact_ipv6_hosts_survive_django_host_validation(self):
        host='[2001:0DB8:0000:0:0:0:0:1]'
        action=SUMMARY+'''
from django.http import HttpRequest
request=HttpRequest()
request.META["HTTP_HOST"]=os.environ["DJANGO_ALLOWED_HOSTS"]
assert request.get_host()
'''
        completed,data=self.run_child(action,changes={'DJANGO_ALLOWED_HOSTS':host})
        self.assertEqual(completed.returncode,0,data)
        self.assertEqual(data['result']['hosts'],[host.lower()])

    def test_development_and_sqlite_profiles_use_redirected_nonoverriding_dotenv(self):
        for profile in ('config.settings.dev','config.settings.test_sqlite'):
            completed,data=self.run_child(changes={'DJANGO_SETTINGS_MODULE':profile},dotenv=True)
            self.assertEqual(completed.returncode,0,data)
            result=data['result']
            self.assertTrue(result['debug'])
            self.assertEqual(result['google_client'],'fixture-dotenv-client')
            self.assertEqual(result['hosts'],['localhost','127.0.0.1'])
            self.assertFalse(result['security']['SESSION_COOKIE_SECURE'])
            self.assertEqual(result['engine'],'django.db.backends.sqlite3')
            self.assertEqual(len(data['dotenv_calls']),1)
            if profile.endswith('test_sqlite'):
                self.assertEqual(result['db_name'],':memory:')
                self.assertTrue(result['test_secret'])
                self.assertNotEqual(result['media'],str(BACKEND/'media'))
            else:self.assertEqual(result['db_name'],str(BACKEND/'db.sqlite3'))
        completed,data=self.run_child(changes={'DJANGO_SETTINGS_MODULE':'config.settings.dev','GOOGLE_OAUTH_CLIENT_ID':'process-wins'},dotenv=True)
        self.assertEqual(completed.returncode,0,data)
        self.assertEqual(data['result']['google_client'],'process-wins')

    def test_wsgi_asgi_and_forced_celery_defaults_and_admission(self):
        for action in ('import config.wsgi','import config.asgi','from config.celery import app\napp.conf.broker_url'):
            with self.subTest(action=action):
                completed,data=self.run_child(action+'\n'+SUMMARY,removed=('DJANGO_SETTINGS_MODULE',))
                self.assertEqual(completed.returncode,0,data)
                self.assertEqual(data['result']['profile'],'config.settings.prod')
                self.refusal(action=action+'\n'+SUMMARY,removed=('DJANGO_SETTINGS_MODULE','DJANGO_DB_NAME'))
        completed,data=self.run_child('from config.celery import app\napp.conf.broker_url\n'+SUMMARY,
            changes={'DJANGO_SETTINGS_MODULE':'config.settings.dev'},dotenv=True)
        self.assertEqual(completed.returncode,0,data)
        self.assertEqual(data['result']['profile'],'config.settings.dev')

    def test_management_default_production_selection_and_static_admission(self):
        # Shell's no-op command exercises the real CLI selector without invoking
        # system checks which can inspect database capabilities after admission.
        action='import runpy\nsys.argv=["manage.py","shell","-c","pass","--verbosity=0"]\nrunpy.run_path("manage.py",run_name="__main__")\n'+SUMMARY
        completed,data=self.run_child(action,removed=('DJANGO_SETTINGS_MODULE',),dotenv=True)
        self.assertEqual(completed.returncode,0,data)
        self.assertEqual(data['result']['profile'],'config.settings.dev')
        action='import runpy\nsys.argv=["manage.py","shell","-c","pass","--verbosity=0","--settings=config.settings.prod"]\nrunpy.run_path("manage.py",run_name="__main__")\n'+SUMMARY
        completed,data=self.run_child(action,removed=('DJANGO_SETTINGS_MODULE',))
        self.assertEqual(completed.returncode,0,data)
        self.assertEqual(data['result']['profile'],'config.settings.prod')
        for command in ('check','collectstatic','migrate','shell','arbitrary-command'):
            for selector in ([], ['--settings=config.settings.prod'], ['--settings','config.settings.prod']):
                arguments=['manage.py',command]
                if command == 'shell':
                    arguments += ['--no-imports','-c',"print('COMMAND_BODY_EXECUTED')"]
                arguments += selector
                action=f'import runpy\nsys.argv={arguments!r}\nrunpy.run_path("manage.py",run_name="__main__")'
                completed,data=self.run_child(action,removed=('DJANGO_DB_NAME',))
                self.assertEqual(completed.returncode,7,data)
                self.assertEqual(data['error'],'ImproperlyConfigured')
                self.assertEqual(data['message'],'Production configuration requires DJANGO_DB_NAME.')
                self.assertIsNone(data['context'])
                self.assertNotIn('COMMAND_BODY_EXECUTED',completed.stdout+completed.stderr)

    def test_management_dispatch_precedence_and_nonproduction_bypass(self):
        cases=(
            (None,[], 'config.settings.dev'),
            ('config.settings.prod',[], 'config.settings.prod'),
            ('config.settings.dev',['--settings=config.settings.prod'],'config.settings.prod'),
            ('config.settings.dev',['--settings','config.settings.prod'],'config.settings.prod'),
            ('config.settings.dev',['--settings=config.settings.prod','--pythonpath=/synthetic/import/path'],'config.settings.prod'),
            ('config.settings.prod',['--settings=config.settings.dev'],'config.settings.dev'),
            ('config.settings.prod',['--settings=config.settings.test_sqlite'],'config.settings.test_sqlite'),
            ('config.settings.prod',['--settings=config.settings.test_postgres'],'config.settings.test_postgres'),
            ('config.settings.prod',['--settings=custom.production_profile'],'custom.production_profile'),
        )
        for environment,selector,expected in cases:
            arguments=['manage.py','synthetic-command','--verbosity=0']+selector
            action=f'''
import runpy
from django.conf import settings
def dispatch(arguments):
    assert arguments == {arguments!r}
    assert "/synthetic/import/path" not in sys.path
    if {expected!r} == "config.settings.prod":
        assert settings.configured
        assert settings.SETTINGS_MODULE == "config.settings.prod"
    else:
        assert not settings.configured
    result.update({{"dispatched":True}})
result={{}}
with patch("django.core.management.execute_from_command_line",dispatch):
    sys.argv={arguments!r}
    runpy.run_path("manage.py",run_name="__main__")
'''
            completed,data=self.run_child(action,
                changes={'DJANGO_SETTINGS_MODULE':environment} if environment else {},
                removed=() if environment else ('DJANGO_SETTINGS_MODULE',))
            self.assertEqual(completed.returncode,0,data)
            self.assertTrue(data['result']['dispatched'])
            if expected != 'config.settings.prod':
                completed,data=self.run_child(action,
                    changes={'DJANGO_SETTINGS_MODULE':environment} if environment else {},
                    removed=('DJANGO_DB_NAME',) if environment else ('DJANGO_DB_NAME','DJANGO_SETTINGS_MODULE'))
                self.assertEqual(completed.returncode,0,data)
        completed,data=self.run_child('import manage\nfrom django.conf import settings\nassert not settings.configured\nresult={"import_only":True}',removed=('DJANGO_DB_NAME',))
        self.assertEqual(completed.returncode,0,data)

    def test_postgres_test_profile_retains_manifest_and_server_guards(self):
        action='''
sys.path.insert(0,str(Path.cwd().parent / "tests/backend"))
import run_database_validation as harness
with patch.object(harness,"load_manifest",return_value={"synthetic":True}) as manifest, patch.object(harness,"verify_server",side_effect=ValueError("Synthetic server verification refusal.")) as server:
    try:
        import config.settings.test_postgres
    except ValueError as error:
        assert str(error)=="Synthetic server verification refusal."
    else:
        raise AssertionError("Guarded PostgreSQL profile bypassed server verification.")
    assert manifest.call_count==1 and server.call_count==1
result={"guards":True}
'''
        completed,data=self.run_child(action,changes={'DJANGO_SETTINGS_MODULE':'config.settings.test_postgres'},dotenv=True)
        self.assertEqual(completed.returncode,0,data)
        self.assertTrue(data['result']['guards'])
