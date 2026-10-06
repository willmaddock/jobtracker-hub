"""Own a socket-only PostgreSQL 17 cluster, validate, then destroy only that run.

Usage: backend/venv/bin/python tests/backend/run_database_validation.py
       --postgres-bin /opt/homebrew/opt/postgresql@17/bin --plan extraction
No existing cluster, keepdb or parallel clones are accepted. Logs go to --report-dir
(default: a fresh temporary evidence directory, retained after cluster cleanup).
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_ENV = "JTH_POSTGRES_MANIFEST"


def private_path(path, *, directory=True):
    path = Path(path)
    info = path.lstat()
    if path.is_symlink() or path.resolve() != path or info.st_uid != os.getuid():
        raise ValueError("Validation path is not canonical and owned")
    if directory and not stat.S_ISDIR(info.st_mode):
        raise ValueError("Expected a validation directory")
    if info.st_mode & 0o077:
        raise ValueError("Validation path is not private")
    return path


def load_manifest(path=None):
    path = path or os.environ.get(MANIFEST_ENV)
    if not path:
        raise ValueError("Harness manifest required")
    path = private_path(path, directory=False)
    run = json.loads(path.read_text())
    if set(run) != {"root", "data", "socket", "role", "database", "system_id", "bin"}:
        raise ValueError("Invalid validation manifest")
    root = private_path(run["root"])
    if root.parent != Path("/private/tmp") or not re.fullmatch(r"jth-pg-[a-z0-9_]+", root.name):
        raise ValueError("Unexpected validation root")
    if path != root / "manifest.json":
        raise ValueError("Manifest must belong to validation root")
    for name, suffix in (("data", "data"), ("socket", "socket")):
        if Path(run[name]) != root / suffix:
            raise ValueError("Unexpected validation child")
        private_path(run[name])
    token = root.name.removeprefix("jth-pg-")
    if run["role"] != "jth_" + token or run["database"] != "test_jth_" + token:
        raise ValueError("Unexpected role/database identity")
    if not re.fullmatch(r"[0-9]+", run["system_id"]):
        raise ValueError("Invalid cluster identity")
    if (Path(run["data"]) / "PG_VERSION").read_text().strip() != "17":
        raise ValueError("PostgreSQL 17 required")
    return run


def clean_environment():
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("PG") and k not in {"DATABASE_URL", "DJANGO_SETTINGS_MODULE", MANIFEST_ENV}}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def sql(run, query):
    return subprocess.check_output([
        str(Path(run["bin"]) / "psql"), "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1",
        "-h", run["socket"], "-p", "5432", "-U", run["role"], "-d", "postgres", "-c", query,
    ], env=clean_environment(), text=True, timeout=10).strip()


def verify_server(run):
    actual = sql(run, "SELECT json_build_object('data', current_setting('data_directory'), "
        "'socket', current_setting('unix_socket_directories'), 'listen', current_setting('listen_addresses'), "
        "'role', current_user, 'version', current_setting('server_version_num'), "
        "'system_id', (SELECT system_identifier::text FROM pg_control_system()))")
    actual = json.loads(actual)
    if (actual["data"] != run["data"] or actual["socket"] != run["socket"] or
        actual["listen"] != "" or actual["role"] != run["role"] or
        int(actual["version"]) // 10000 != 17 or actual["system_id"] != run["system_id"]):
        raise ValueError("Live PostgreSQL identity does not match owned run")
    return actual


def assert_fresh_database(run):
    verify_server(run)
    if sql(run, "SELECT count(*) FROM pg_database WHERE datname = '" + run["database"] + "'") != "0":
        raise ValueError("Refusing an existing validation database")


class ValidationDatabaseCreationFailure(RuntimeError):
    """Creation failed; no pre-existing database may be destroyed or reused."""


def creation_class():
    from django.db import DatabaseError
    from django.db.backends.postgresql.creation import DatabaseCreation
    from django.db.backends.base.creation import BaseDatabaseCreation

    class FailClosedCreation(DatabaseCreation):
        def _create_test_db(self, verbosity, autoclobber, keepdb=False):
            if keepdb:
                raise ValueError("Validation database reuse is forbidden")
            name = self._get_test_db_name()
            parameters = {"dbname": self.connection.ops.quote_name(name),
                          "suffix": self.sql_table_creation_suffix()}
            with self._nodb_cursor() as cursor:
                try:
                    # Execute exactly one CREATE. Do not enter Django's prompt,
                    # autoclobber, DROP or retry path, even with --noinput.
                    BaseDatabaseCreation._execute_create_test_db(self, cursor, parameters, keepdb=False)
                except DatabaseError as error:
                    sqlstate = getattr(error.__cause__, "sqlstate", None)
                    raise ValidationDatabaseCreationFailure(
                        f"Validation database creation safety failure (SQLSTATE {sqlstate or 'unknown'}); "
                        "no database was dropped or reused") from error
            return name
    return FailClosedCreation


# Imported only when Django selects this harness-only runner.
def runner_class():
    from django.test.runner import DiscoverRunner
    class GuardedRunner(DiscoverRunner):
        def __init__(self, *args, **kwargs):
            if kwargs.get("keepdb") or kwargs.get("parallel", 0) > 1:
                raise ValueError("keepdb and parallel database cloning are forbidden")
            super().__init__(*args, **kwargs)
        def setup_databases(self, **kwargs):
            run = load_manifest()
            from django.conf import settings
            db = settings.DATABASES["default"]
            if (db["ENGINE"] != "django.db.backends.postgresql" or db["NAME"] != "postgres" or
                db["HOST"] != run["socket"] or db["USER"] != run["role"] or
                str(db["PORT"]) != "5432" or db["TEST"]["NAME"] != run["database"]):
                raise ValueError("Unexpected Django validation database configuration")
            assert_fresh_database(run)
            from django.db import connections
            connection = connections["default"]
            original_creation = connection.creation
            connection.creation = creation_class()(connection)
            try:
                return super().setup_databases(**kwargs)
            finally:
                connection.creation = original_creation
        def teardown_databases(self, old_config, **kwargs):
            verify_server(load_manifest())
            return super().teardown_databases(old_config, **kwargs)
    return GuardedRunner


def __getattr__(name):
    if name == "GuardedRunner":
        return runner_class()
    raise AttributeError(name)


def cleanup(run):
    run = load_manifest(Path(run["root"]) / "manifest.json")
    verify_server(run)
    subprocess.run([str(Path(run["bin"]) / "pg_ctl"), "-D", run["data"],
                    "-m", "fast", "-w", "stop"], check=True, timeout=40)
    # Verify the stopped cluster's control identity as well as its private paths.
    load_manifest(Path(run["root"]) / "manifest.json")
    control = subprocess.check_output([str(Path(run["bin"]) / "pg_controldata"), run["data"]],
                                     text=True, timeout=10, env=clean_environment())
    match = re.search(r"Database system identifier:\s+(\d+)", control)
    if not match or match[1] != run["system_id"] or (Path(run["data"]) / "postmaster.pid").exists():
        raise ValueError("Stopped cluster identity could not be verified")
    shutil.rmtree(run["root"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-bin", help="Defaults to brew --prefix postgresql@17/bin")
    parser.add_argument("--plan", choices=["runtime", "postgres", "extraction"], required=True)
    parser.add_argument("--report-dir")
    args = parser.parse_args()
    prefix = subprocess.check_output([shutil.which("brew") or "/opt/homebrew/bin/brew",
                                      "--prefix", "postgresql@17"], text=True).strip()
    binary = Path(args.postgres_bin or str(Path(prefix) / "bin")).resolve()
    if binary != (Path(prefix) / "bin").resolve():
        raise ValueError("Only installed Homebrew postgresql@17 binaries are accepted")
    version = subprocess.check_output([str(binary / "postgres"), "--version"], text=True).strip()
    if version != "postgres (PostgreSQL) 17.11 (Homebrew)":
        raise ValueError("Installed PostgreSQL must be exactly 17.11 (Homebrew)")
    env = clean_environment()
    env["PSYCOPG_IMPL"] = "python"
    libdir = Path(subprocess.check_output([str(binary / "pg_config"), "--libdir"], text=True).strip())
    for resource in (libdir / "libpq.dylib", Path(subprocess.check_output(
            [str(binary / "pg_config"), "--sharedir"], text=True).strip()) / "timezone"):
        if not resource.exists():
            raise ValueError(f"Installed Homebrew runtime resource is missing: {resource}")
    env["DYLD_LIBRARY_PATH"] = str(libdir)
    python = str(ROOT / "backend" / "venv" / "bin" / "python")
    driver = subprocess.check_output([python, "-c", "import psycopg; assert psycopg.__version__ == '3.3.6'; print(psycopg.__version__)"], env=env, text=True).strip()
    report = Path(args.report_dir).resolve() if args.report_dir else Path(tempfile.mkdtemp(prefix="jth-pg-evidence-"))
    report.mkdir(exist_ok=True)
    print(f"Evidence directory: {report}\n{version}; psycopg {driver}", flush=True)
    root = Path(tempfile.mkdtemp(prefix="jth-pg-", dir="/private/tmp"))
    token = root.name.removeprefix("jth-pg-")
    data, socket = root / "data", root / "socket"
    socket.mkdir(mode=0o700)
    run = {"root": str(root), "data": str(data), "socket": str(socket),
           "role": "jth_" + token, "database": "test_jth_" + token,
           "system_id": "", "bin": str(binary)}
    started = False
    results = []
    try:
        subprocess.run([str(binary / "initdb"), "-D", str(data), "-U", run["role"],
            "--encoding=UTF8", "--locale=C", "--auth-local=trust", "--auth-host=reject"], check=True, env=env, timeout=60)
        options = f"-c listen_addresses='' -c unix_socket_directories={socket} -c unix_socket_permissions=0700"
        subprocess.run([str(binary / "pg_ctl"), "-D", str(data), "-l", str(report / "server.log"),
                        "-o", options, "-w", "start"], check=True, env=env, timeout=40)
        started = True
        run["system_id"] = sql(run, "SELECT system_identifier FROM pg_control_system()")
        manifest = root / "manifest.json"
        descriptor = os.open(manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(run, stream)
        env[MANIFEST_ENV] = str(manifest)
        verify_server(load_manifest(manifest))
        (report / "runtime.json").write_text(json.dumps({"postgres": version, "driver": driver, "identity": run}, indent=2))
        suites = ["postings.tests.test_retained_extractions", "postings.tests.test_retained_extraction_producer",
                  "postings.tests.test_retained_extraction_inspection", "postings.tests.test_retained_extraction_api",
                  "postings.tests.test_extract_retained_job_alerts_command", "email_sync.tests.test_retention"]
        assert_fresh_database(run)
        sql(run, 'CREATE DATABASE "' + run["database"] + '"')
        sql(run, 'DROP DATABASE "' + run["database"] + '"')
        assert_fresh_database(run)
        results.append({"name": "runtime-proof", "exit": 0})
        print("Runtime proof: private socket, identity, create/drop verified", flush=True)
        commands = [] if args.plan == "runtime" else [
            ("focused", "test_postgres", ["test", "postings.tests.test_postgres_extraction", "--noinput", "--verbosity=2"], 180),
            ("existing", "test_postgres", ["test", *suites, "--noinput", "--verbosity=2"], 300),
            ("postgres-check", "test_postgres", ["check"], 60),
            ("postings-drift", "test_postgres", ["makemigrations", "postings", "--check", "--dry-run"], 60),
            ("global-drift", "test_postgres", ["makemigrations", "--check", "--dry-run"], 60),
            ("sqlite", "test_sqlite", ["test", "--noinput"], 600),
            ("sqlite-check", "test_sqlite", ["check"], 60),
        ]
        if args.plan == "postgres":
            commands = [entry for entry in commands if entry[1] == "test_postgres"]
        for name, settings, command, timeout in commands:
            verify_server(load_manifest(manifest))
            invocation = [python, "manage.py", *command, "--settings=config.settings." + settings]
            with (report / (name + ".log")).open("w") as stream:
                completed = subprocess.run(invocation, cwd=ROOT / "backend", env=env,
                    stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
            output = (report / (name + ".log")).read_text()
            expected_drift = (name == "global-drift" and completed.returncode == 1 and
                "Alter field provider on emailaccount" in output and output.count("Migrations for '") == 1 and
                output.count("Alter field ") == 1 and "Migrations for 'email_sync'" in output)
            results.append({"name": name, "exit": completed.returncode, "known_drift": expected_drift})
            print(f"{name}: exit {completed.returncode}" + (" (known provider drift)" if expected_drift else ""), flush=True)
            if completed.returncode and not expected_drift:
                print(output, flush=True)
                raise RuntimeError(f"Validation failed: {name}; evidence preserved at {report}")
        (report / "results.json").write_text(json.dumps(results, indent=2))
    finally:
        (report / "results.json").write_text(json.dumps(results, indent=2))
        if started:
            if not (root / "manifest.json").exists():
                # Never delete an unverifiable cluster after incomplete startup.
                print(f"Incomplete ownership manifest; preserve {root} for inspection", flush=True)
            else:
                cleanup(run)
                print("Verified owned cluster stopped and removed", flush=True)
        else:
            print(f"Startup failed; preserve {root} for inspection", flush=True)


if __name__ == "__main__":
    main()
