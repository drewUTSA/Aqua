"""Exercise the real installer with disposable resource names and fake secrets.

Trusted Docker operator only. Never uses the fixed live app database names.
No host port or external network is used, even during bootstrap.
"""

import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile

from storage_deployment_support import load, cleanup, verify_export

ROOT = Path(__file__).resolve().parents[2]


def check(image: str) -> dict:
    run_id = "aqua-storage-check-" + secrets.token_hex(12)
    root = Path(tempfile.mkdtemp(prefix=".storage-check-", dir=ROOT))
    os.chmod(root, 0o755)  # Only fake fixtures; postgres UID must read HBA.
    report = {"run": run_id, "status": "failed"}
    container, volume, sockets = (run_id + x for x in ("-pg", "-data", "-sockets"))
    private = load("private", ROOT / "ops/appdb/private.py")
    sys.modules["private"] = private
    manager = load("aqua_test_manager", ROOT / "ops/appdb/manage.py")
    try:
        (root / "secrets").mkdir(mode=0o700)
        private.directory = lambda: root / "secrets"
        manager.directory = private.directory
        manager.ROOT = root
        manager.CONTAINER, manager.VOLUME, manager.SOCKET_VOLUME = (
            container,
            volume,
            sockets,
        )
        manager.BACKEND_IMAGE = image

        def fixture_run(args, data=None, timeout=60):
            result = subprocess.run(
                args,
                input=data,
                capture_output=True,
                cwd=root,
                timeout=timeout,
                env={
                    **os.environ,
                    "AQUA_PRIVATE_STORAGE_DIR": str(private.directory()),
                },
            )
            if result.returncode:
                diagnostic = result.stderr.decode(errors="replace")[-1800:]
                for value in private.credentials().values():
                    diagnostic = diagnostic.replace(value, "[fixture-secret]")
                report["fixture_error"] = diagnostic
                raise RuntimeError("isolated_deployment_command_failed")
            return result.stdout

        manager.run = fixture_run
        for name in ("ops/appdb/pg_hba.conf", "backend/migrations/bootstrap.psql"):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
            os.chmod(target, 0o644)
        compose = (ROOT / "compose.appdb.yml").read_text()
        for before, after in [
            ("aqua-app-storage", run_id),
            ("aqua-app-db", container),
            ("aqua_app_data", volume),
            ("aqua_app_sockets", sockets),
        ]:
            compose = compose.replace(before, after)
        (root / "compose.appdb.yml").write_text(compose)
        report["bootstrap"] = manager.bootstrap()
        manager.docker(
            "run",
            "--rm",
            "--network=none",
            "--mount",
            "source=" + sockets + ",target=/run/aqua-app-db,readonly",
            "--read-only",
            "--cap-drop=ALL",
            "--memory=128m",
            "--cpus=1",
            "--pids-limit=32",
            "--env-file",
            str(private.directory() / "migrator.env"),
            "--entrypoint=python",
            image,
            "-c",
            "import os,psycopg; psycopg.connect(os.environ['APP_MIGRATOR_DATABASE_URL'],connect_timeout=2).close()",
        )
        for _ in range(2):
            assert manager.migrate()["schema_version"] == 4
        # The image gets only the generated runtime fixture DSN, no live env.
        program = (ROOT / "tools/checks/storage_probe.py").read_text()
        result = manager.docker(
            "run",
            "--rm",
            "--network=none",
            "--mount",
            "source=" + sockets + ",target=/run/aqua-app-db,readonly",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--memory=256m",
            "--cpus=1",
            "--pids-limit=64",
            "--env-file",
            str(private.directory() / "runtime.env"),
            "--entrypoint=python",
            image,
            "-c",
            program,
        )
        assert result.strip() == b"isolated_runtime_ready_and_ddl_denied"
        report["backup_export"] = verify_export(ROOT, container)
        item = json.loads(manager.docker("inspect", container))[0]
        assert item["HostConfig"]["ReadonlyRootfs"]
        assert item["Config"]["User"] == "999:999"
        assert item["HostConfig"]["NetworkMode"] == "none"
        assert not item["HostConfig"]["PortBindings"]
        report.update(
            status="passed",
            repeated_migration="passed",
            password_auth="passed",
            runtime_ddl_denial_and_recovery="passed",
            network_disabled=True,
            no_tcp_port=True,
            real_data_accessed=False,
        )
    except Exception as error:
        # Only category in shared evidence. Driver errors could contain a DSN.
        report["error_type"] = type(error).__name__
        raise
    finally:
        cleanup(root, run_id, container, volume, sockets, report)
        print(json.dumps(report))
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="aqua-runtime:check")
    args = parser.parse_args()
    raise SystemExit(check(args.image)["status"] != "passed")
