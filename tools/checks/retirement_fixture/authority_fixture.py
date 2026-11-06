"""Explicit disposable independent-authority rehearsal, never production DDL.

No execution by default. Source and current passed P11 image are hash-bound.
This SQL/restore rehearsal does not prove actual host append-only storage,
checkpoint filesystem durability, HTTP deletion or production activation.
"""

import argparse
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import selectors
import signal
import subprocess
import sys
import tarfile
import time

CANONICAL_RUN = "p11a-checks-20261031031705543-609efe20"
MANIFEST_SHA = "9933d1cae00f16ef9eca4f686ce83ecbbf3655e91c1dc64b5ce2eb3893013342"
SUMMARY_SHA = "9e401da14084e193f5bdfd8d6bb7d233f95ae81199a82f3d2535f5e311a05c50"
IMAGE = "sha256:1f541b30b479760c32a7a7d35adc2cfad4082ab465157510541ac7e49a0c9e2f"
FILES = (
    "authority_fixture.py",
    "authority_pg_cases.py",
    "authority-bootstrap.psql",
    "authority-schema.psql",
    "app-intent-proof-fragment.psql",
    "backend-sources/retirement/fingerprints.py",
    "backend-sources/retirement/pages.py",
    "backend-sources/retirement/intents.py",
    "backend-sources/retirement/interlock.py",
    "backend-sources/retirement/checkpoint.py",
    "backend-sources/retirement/publisher.py",
    "backend-sources/retirement/revision.py",
    "backend-sources/retirement/client.py",
    "fingerprint_test.py",
    "page_test.py",
    "interlock_test.py",
    "intent_test.py",
    "checkpoint_test.py",
    "protocol_model_test.py",
    "authority_fixture_test.py",
    "revision_test.py",
    "client_test.py",
    "authority-hba.fragment",
)
INSTALLATION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
KEY_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
COMMITMENT = hmac.new(
    b"synthetic-fixture-HMAC-key-only!".ljust(32, b"0"),
    b"AQUA:retirement-key-check:v1\x00",
    hashlib.sha256,
).hexdigest()
INIT = """import psycopg
from storage.migrate import apply,migrations
with psycopg.connect('host=/run/aqua-app-db port=5432 dbname=aqua_app user=aqua_app_migrator password=fixture-only sslmode=disable',autocommit=True,connect_timeout=3) as c:
 assert apply(c,migrations())==8
"""
WRAPPER = """import json,runpy,sys
sys.argv=sys.argv[1:]
try:runpy.run_path(sys.argv[0],run_name='__main__')
except BaseException as error:
 trace=error.__traceback__
 while trace.tb_next:trace=trace.tb_next
 print(json.dumps({'status':'failed','error_type':type(error).__name__,'file':trace.tb_frame.f_code.co_filename.rsplit('/',1)[-1],'line':trace.tb_lineno}))
"""
NATIVE_PROGRAM = """import io,json,unittest
suite=unittest.defaultTestLoader.discover('/checks/private',pattern='*_test.py')
result=unittest.TextTestRunner(stream=io.StringIO()).run(suite)
print(json.dumps({'status':'passed' if result.wasSuccessful() else 'failed','tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped)}))
"""
FAULT_INSTALL = b"""
SET ROLE aqua_retirement_owner;
CREATE FUNCTION retirement.fixture_commit_failure() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.intent_id='00000000-0000-4000-8000-000000000004'::uuid THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='synthetic_commit_failure';
 END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER fixture_commit_failure AFTER INSERT ON retirement.journal
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION retirement.fixture_commit_failure();
RESET ROLE;
"""
FAULT_REMOVE = b"SET ROLE aqua_retirement_owner; DROP TRIGGER fixture_commit_failure ON retirement.journal; DROP FUNCTION retirement.fixture_commit_failure(); RESET ROLE;"
STATE_QUERY = b"""
SELECT encode(sha256(convert_to(string_agg(name||':'||body,E'\\n' ORDER BY name),'UTF8')),'hex') FROM (
 SELECT 'control' name, jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text)::text body FROM retirement.control t
 UNION ALL SELECT 'owners',jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text)::text FROM retirement.owners t
 UNION ALL SELECT 'intents',jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text)::text FROM retirement.intents t
 UNION ALL SELECT 'pages',jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text)::text FROM retirement.pages t
 UNION ALL SELECT 'fingerprints',jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text)::text FROM retirement.fingerprints t
 UNION ALL SELECT 'journal',jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text)::text FROM retirement.journal t
) x;
"""


def require(condition):
    if not condition:
        raise RuntimeError("authority_fixture_invariant_denied")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def bounded(path, limit):
    info = path.lstat()
    require(
        path.is_file()
        and not path.is_symlink()
        and path.resolve() == path
        and info.st_nlink == 1
        and 0 < info.st_size <= limit
    )
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    require(len(data) == info.st_size)
    return data


def sources(root, expected):
    manifest_raw = bounded(root / "private-sources.json", 16384)
    require(re.fullmatch("[a-f0-9]{64}", expected) and digest(manifest_raw) == expected)
    manifest = json.loads(manifest_raw)
    require(type(manifest) is dict and set(manifest) == set(FILES))
    data = {}
    for name in FILES:
        raw = bounded(root / name, 131072)
        require(manifest[name] == digest(raw))
        data[name] = raw
    return data


def canonical(directory):
    require(
        directory == Path("/srv/bank-ai/.check-results") / CANONICAL_RUN
        and directory.resolve() == directory
        and not directory.is_symlink()
    )
    manifest_raw = bounded(directory / "manifest.json", 1048576)
    summary_raw = bounded(directory / "summary.json", 1048576)
    require(digest(manifest_raw) == MANIFEST_SHA and digest(summary_raw) == SUMMARY_SHA)
    manifest, summary = json.loads(manifest_raw), json.loads(summary_raw)
    require(
        summary["status"] == "passed"
        and summary["backend_image"] == IMAGE
        and summary["runtime_files"] == 167
        and summary["schema_version"] == 8
        and summary["production_changed"] is False
        and summary["existing_running_containers_unchanged"] is True
        and len(manifest["files"]) == 374
        and len(summary["checks"]) == 25
        and set(summary["checks"]) == set(manifest["required_gates"])
        and all(row["status"] == "passed" for row in summary["checks"].values())
    )
    source = directory / "source"
    require(source.resolve() == source and source.is_dir() and not source.is_symlink())
    observed = set()
    for path in source.rglob("*"):
        require(not path.is_symlink())
        if path.is_file():
            observed.add(path.relative_to(source).as_posix())
    require(observed == set(manifest["files"]))
    total = 0
    for name, expected in manifest["files"].items():
        require(
            re.fullmatch(r"[A-Za-z0-9_./-]+", name)
            and not name.startswith("/")
            and ".." not in name.split("/")
        )
        raw = bounded(source / name, 2097152)
        total += len(raw)
        require(total <= 16777216 and digest(raw) == expected)
    return source


def archive(files):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as bundle:
        for name, raw in sorted(files.items()):
            if not name.endswith(".py"):
                continue
            info = tarfile.TarInfo(name)
            info.size, info.uid, info.gid, info.mode = len(raw), 1000, 1000, 0o644
            bundle.addfile(info, io.BytesIO(raw))
    require(stream.tell() <= 1048576)
    return stream.getvalue()


def dump_application(pg, docker_env):
    # Read stdout incrementally with a fixed memory/time cap. Never write a plain
    # dump to host/container disk or print it; only synthetic metadata is present.
    process = subprocess.Popen(
        [
            "/usr/bin/docker",
            "--host=unix:///var/run/docker.sock",
            "exec",
            pg,
            "pg_dump",
            "-U",
            "postgres",
            "-d",
            "aqua_app",
            "--clean",
            "--if-exists",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=docker_env,
    )
    deadline, output = time.monotonic() + 15, bytearray()
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while True:
            require(time.monotonic() < deadline)
            if not selector.select(min(0.25, deadline - time.monotonic())):
                continue
            block = os.read(process.stdout.fileno(), 65536)
            if not block:
                break
            require(len(output) + len(block) <= 8 * 1024 * 1024)
            output.extend(block)
        require(
            process.wait(timeout=max(0.01, deadline - time.monotonic())) == 0 and output
        )
        return bytes(output)
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        process.stdout.close()


def native_run(root, directory, output, source_hash):
    """One existing image runner only: no PostgreSQL or SQL/role creation."""
    require(
        root.parent == Path("/srv/bank-ai/.check-results")
        and root.resolve() == root
        and re.fullmatch(r"p11bc-authority-[0-9]{17}-[a-f0-9]{8}", root.name)
        and root.stat().st_uid == 1000
        and (root.stat().st_mode & 0o7777) == 0o700
        and output == root / "native-report.json"
        and not output.exists()
    )
    files = sources(root, source_hash)
    source = canonical(directory)
    sys.path.insert(0, str(source / "tools/checks"))
    from p05_browser_resources import Resources
    from p05_browser_docker import create, docker

    resources = Resources("aqua-p05-browser-" + secrets.token_hex(12))
    report = {
        "status": "failed",
        "kind": "native_offline_private_authority_guards",
        "run": root.name,
        "fixture_run": resources.name,
        "backend_image": IMAGE,
        "canonical_run": CANONICAL_RUN,
        "private_sources_sha256": source_hash,
        "network": "none",
        "production_changed": False,
        "PG_DDL_executed": False,
        "actual_key_file_reads": 0,
        "actual_provider_calls": 0,
        "protected_checkpoint_storage_proven": False,
    }
    started = time.monotonic()
    try:
        resources.preparing("container", resources.name + "-api")
        runner = create(
            resources.name + "-api",
            IMAGE,
            "--user=1000:1000",
            "--tmpfs=/tmp:rw,nosuid,nodev,size=134217728,mode=1777",
            "--tmpfs=/checks:rw,nosuid,nodev,size=67108864,mode=0777",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-e",
            "PYTHON_DOTENV_DISABLED=1",
            "--workdir=/app",
            "--entrypoint=/bin/sleep",
            command=("60",),
        )
        resources.uncertain.discard(resources.name + "-api")
        docker("start", runner, timeout=10)
        unpack = "import io,sys,tarfile;tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read(1048577))).extractall('/checks/private',filter='data')"
        docker(
            "exec",
            "-i",
            runner,
            "python",
            "-E",
            "-s",
            "-B",
            "-c",
            unpack,
            data=archive(files),
            timeout=10,
        )
        native = json.loads(
            docker(
                "exec",
                "--workdir=/app",
                runner,
                "python",
                "-E",
                "-s",
                "-B",
                "-c",
                NATIVE_PROGRAM,
                timeout=15,
            )
        )
        report["native_offline"] = native
        require(
            native
            == {
                "status": "passed",
                "tests": 61,
                "failures": 0,
                "errors": 0,
                "skipped": 0,
            }
        )
        report["status"] = "passed"
    except BaseException as error:
        report["error_type"] = type(error).__name__
    finally:
        remaining = resources.cleanup()
        report["cleanup"] = (
            "removed_and_absence_confirmed" if not remaining else "incomplete"
        )
        report["remaining_ids"] = remaining
        if remaining:
            report["status"] = "failed"
        report["seconds"] = round(time.monotonic() - started, 2)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
    return report


def run(root, directory, output, source_hash):
    require(
        root.parent == Path("/srv/bank-ai/.check-results")
        and root.resolve() == root
        and re.fullmatch(r"p11bc-authority-[0-9]{17}-[a-f0-9]{8}", root.name)
        and root.stat().st_uid == 1000
        and (root.stat().st_mode & 0o7777) == 0o700
        and output == root / "report.json"
        and not output.exists()
    )
    files = sources(root, source_hash)
    source = canonical(directory)
    sys.path.insert(0, str(source / "tools/checks"))
    from p05_browser_resources import Resources
    from p05_browser_docker import DOCKER_ENV, docker

    resources = Resources("aqua-p05-browser-" + secrets.token_hex(12))
    report = {
        "status": "failed",
        "kind": "private_independent_authority_SQL_rehearsal",
        "run": root.name,
        "fixture_run": resources.name,
        "canonical_run": CANONICAL_RUN,
        "backend_image": IMAGE,
        "canonical_manifest_sha256": MANIFEST_SHA,
        "canonical_summary_sha256": SUMMARY_SHA,
        "private_sources_sha256": source_hash,
        "network": "none",
        "production_changed": False,
        "real_provider_calls": 0,
        "key_file_reads": 0,
        "protected_checkpoint_storage_proven": False,
        "application_deletion_paths_proven": False,
        "activation_authorized": False,
        "limits": {
            "seconds": 120,
            "active_containers": 2,
            "postgres_data_bytes": 536870912,
            "container_memory_bytes": 1073741824,
            "dump_bytes": 8388608,
            "dump_seconds": 15,
        },
        "cases": [],
    }

    def sql(database, statement):
        require(
            database in {"postgres", "aqua_app", "aqua_retirement"}
            and len(statement) <= 8 * 1024 * 1024
        )
        result = subprocess.run(
            [
                "/usr/bin/docker",
                "--host=unix:///var/run/docker.sock",
                "exec",
                "-i",
                resources.name + "-pg",
                "psql",
                "-X",
                "-q",
                "-A",
                "-t",
                "-v",
                "ON_ERROR_STOP=1",
                "-v",
                "VERBOSITY=sqlstate",
                "-U",
                "postgres",
                "-d",
                database,
            ],
            input=statement,
            capture_output=True,
            timeout=15,
            env=DOCKER_ENV,
        )
        require(len(result.stdout) <= 1048576 and len(result.stderr) <= 1048576)
        if result.returncode:
            states = re.findall(rb"ERROR:\s*([0-9A-Z]{5})\b", result.stderr)
            report["SQL_failure"] = {
                "sqlstate": states[-1].decode("ascii") if states else None
            }
            raise RuntimeError("authority_fixture_SQL_failed")
        return result.stdout

    def cases(mode):
        result = json.loads(
            docker(
                "exec",
                "--workdir=/app",
                runner,
                "python",
                "-E",
                "-s",
                "-B",
                "-c",
                WRAPPER,
                "/checks/private/authority_pg_cases.py",
                mode,
                timeout=30,
            )
        )
        if result.get("status") != "passed":
            report["case_failure"] = {
                key: result[key]
                for key in ("error_type", "file", "line")
                if key in result
            }
            raise RuntimeError("authority_SQL_case_failed")
        require(
            result["mode"] == mode
            and result["protected_checkpoint_storage_proven"] is False
        )
        report["cases"].append(result)

    started = time.monotonic()
    previous = signal.signal(
        signal.SIGALRM, lambda *args: (_ for _ in ()).throw(TimeoutError())
    )
    signal.alarm(120)
    try:
        runner = resources.provision(IMAGE, report)
        report["step"] = "schema8"
        docker(
            "exec",
            "--workdir=/app",
            runner,
            "python",
            "-E",
            "-s",
            "-B",
            "-c",
            INIT,
            timeout=30,
        )
        report["step"] = "independent_bootstrap"
        prefix = b"\\set writer_password 'fixture-only'\n\\set recovery_password 'fixture-only'\n\\set checkpoint_password 'fixture-only'\n"
        sql("postgres", prefix + files["authority-bootstrap.psql"])
        prefix = f"\\set installation_id '{INSTALLATION}'\n\\set identity_key_id '{KEY_ID}'\n\\set key_commitment '{COMMITMENT}'\n".encode()
        sql("postgres", prefix + files["authority-schema.psql"])
        hba = b"local all postgres peer\n"
        for role in ("aqua_app_runtime", "aqua_app_migrator", "aqua_app_backup"):
            hba += f"local aqua_app {role} scram-sha-256\n".encode()
        authority_hba = (
            b"\n".join(
                line
                for line in files["authority-hba.fragment"].splitlines()
                if line and not line.startswith(b"#")
            )
            + b"\n"
        )
        require(
            authority_hba
            == b"local aqua_retirement aqua_retirement_writer scram-sha-256\nlocal aqua_retirement aqua_retirement_recovery scram-sha-256\nlocal aqua_retirement aqua_retirement_checkpoint scram-sha-256\n"
        )
        hba += authority_hba
        hba += b"local all all reject\nhost all all 0.0.0.0/0 reject\nhost all all ::/0 reject\n"
        docker(
            "exec",
            "-i",
            resources.name + "-pg",
            "tee",
            "/var/lib/postgresql/data/pg_hba.conf",
            data=hba,
        )
        sql("postgres", b"SELECT pg_reload_conf();")
        # A NEW owner-created function must retain zero PUBLIC/role execution;
        # this proves the global default revoke, not only installed-function ACLs.
        sql(
            "aqua_retirement",
            b"SET ROLE aqua_retirement_owner; CREATE FUNCTION retirement.fixture_default_acl_sentinel() RETURNS integer LANGUAGE sql AS 'SELECT 1'; RESET ROLE;",
        )
        sql(
            "aqua_app",
            b"SET ROLE aqua_app_owner;\n"
            + files["app-intent-proof-fragment.psql"]
            + b"\nRESET ROLE;",
        )
        unpack = "import io,sys,tarfile;tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read(1048577))).extractall('/checks/private',filter='data')"
        docker(
            "exec",
            "-i",
            runner,
            "python",
            "-E",
            "-s",
            "-B",
            "-c",
            unpack,
            data=archive(files),
        )
        report["step"] = "native_offline_guards"
        native = json.loads(
            docker(
                "exec",
                "--workdir=/app",
                runner,
                "python",
                "-E",
                "-s",
                "-B",
                "-c",
                NATIVE_PROGRAM,
                timeout=15,
            )
        )
        require(
            native
            == {
                "status": "passed",
                "tests": 61,
                "failures": 0,
                "errors": 0,
                "skipped": 0,
            }
        )
        report["native_offline"] = native
        report["step"] = "before_retirement_app_dump"
        dump = dump_application(resources.name + "-pg", DOCKER_ENV)
        report["app_dump"] = {
            "storage": "memory_only",
            "bytes": len(dump),
            "sha256": digest(dump),
        }
        report["step"] = "SQL_cases"
        cases("suite")
        report["step"] = "deferred_commit_failure"
        sql("aqua_retirement", FAULT_INSTALL)
        cases("commit-failure")
        sql("aqua_retirement", FAULT_REMOVE)
        cases("finish-fault")
        cases("reconcile")
        report["step"] = "app_only_restore"
        before = sql("aqua_retirement", STATE_QUERY).strip()
        require(re.fullmatch(rb"[a-f0-9]{64}", before) is not None)
        sql("aqua_app", dump)
        cases("reconcile")
        after = sql("aqua_retirement", STATE_QUERY).strip()
        require(after == before)
        report["independent_store_unchanged_by_app_restore"] = True
        report["independent_store_sha256"] = before.decode("ascii")
        report["status"] = "passed"
    except BaseException as error:
        report["error_type"] = type(error).__name__
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
        remaining = resources.cleanup()
        report["cleanup"] = (
            "removed_and_absence_confirmed" if not remaining else "incomplete"
        )
        report["remaining_ids"] = remaining
        if remaining:
            report["status"] = "failed"
        report["seconds"] = round(time.monotonic() - started, 2)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--execute", action="store_true")
    modes.add_argument("--native-only", action="store_true")
    parser.add_argument("--canonical-directory", type=Path)
    parser.add_argument("--sources-sha256")
    args = parser.parse_args()
    if not args.execute and not args.native_only:
        print(
            json.dumps(
                {"status": "prepared_only", "Docker_actions": 0, "live_DDL": False}
            )
        )
    else:
        here = Path(__file__).resolve().parent
        operation = native_run if args.native_only else run
        result = operation(
            here,
            args.canonical_directory,
            here / ("native-report.json" if args.native_only else "report.json"),
            args.sources_sha256,
        )
        print(
            json.dumps(
                {
                    key: result.get(key)
                    for key in ("status", "step", "cleanup", "remaining_ids")
                }
            )
        )
        raise SystemExit(0 if result["status"] == "passed" else 1)
