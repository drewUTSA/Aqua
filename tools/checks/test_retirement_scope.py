"""Explicit QA locations preserve fixed production defaults and real guards."""

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ops.retirement.operator_scope import Scope, PRODUCTION, BASE, PRODUCTION_PRIVATE
from ops.retirement import maintenance, install_resources, export_resources, recover

RUN = "aqua-retirement-host-" + "1" * 24
IMAGE = "sha256:" + "2" * 64


class ScopeGuards(unittest.TestCase):
    def test_production_cannot_infer_QA_from_ambient_environment(self):
        with patch.dict(
            "os.environ",
            {"AQUA_RETIREMENT_QA_RUN": RUN, "PRIVATE_DATA_DELETE_ENABLED": "false"},
        ):
            self.assertIsNone(PRODUCTION.qa_run)
            self.assertEqual(PRODUCTION.private, PRODUCTION_PRIVATE)
            self.assertEqual(PRODUCTION.socket, "aqua_app_sockets")
            self.assertEqual(
                PRODUCTION.backend_filters(),
                [
                    "--filter",
                    "label=com.docker.compose.project=bank-ai",
                    "--filter",
                    "label=com.docker.compose.service=backend",
                ],
            )

    def test_explicit_empty_QA_cli_rejected_before_private_actions(self):
        from ops.retirement import export, install

        for module, argv in (
            (install, ["install.py", "--execute", "--qa-run", ""]),
            (export, ["export.py", "--action", "head", "--qa-run", ""]),
            (recover, ["recover.py", "--execute", "--qa-run", ""]),
            (maintenance, ["maintenance.py", "--hold", "--qa-run", ""]),
        ):
            with (
                self.subTest(module=module.__name__),
                patch.object(sys, "argv", argv),
                patch.object(module, "read") as private_read,
                patch.object(maintenance, "run") as host,
                patch.object(module.signal, "signal"),
                patch.object(module.signal, "alarm"),
            ):
                with self.assertRaisesRegex(ValueError, "QA_scope_invalid"):
                    module.main()
                private_read.assert_not_called()
                host.assert_not_called()

    def test_only_closed_run_nonce_scope_is_accepted(self):
        for value in (
            "",
            "production",
            "../production",
            RUN + "/child",
            RUN.upper(),
            "/srv/bank-ai",
            True,
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Scope(value)
        scope = Scope(RUN)
        self.assertEqual(scope.parent, BASE / RUN)
        self.assertEqual(scope.private, BASE / RUN / "installed")
        self.assertEqual(scope.mail, BASE / RUN / "mail")
        self.assertEqual(scope.socket, RUN + "-socket")

    def test_QA_never_reads_actual_crontab_and_cannot_use_other_run_schedule(self):
        scope = Scope(RUN)
        raw = ("no scheduler installed for " + RUN + "\n").encode()
        with (
            patch.object(maintenance, "run") as run,
            patch.object(maintenance, "read", return_value=raw) as read,
        ):
            self.assertEqual(scope.schedule(run, read), raw)
            run.assert_not_called()
            read.assert_called_once_with(scope.parent / "schedule.absent")
        with self.assertRaises(RuntimeError):
            scope.schedule(lambda args: None, lambda path: b"other run")

    def test_QA_root_must_be_canonical_owner1000_private700(self):
        scope = Scope(RUN)
        with (
            patch.object(maintenance.os, "geteuid", return_value=1000),
            patch.object(Path, "resolve", lambda self, strict=True: self),
            patch.object(
                Path,
                "lstat",
                return_value=SimpleNamespace(st_mode=0o40700, st_uid=1000),
            ),
        ):
            scope.validate()
        for mode, uid in ((0o40755, 1000), (0o40700, 0), (0o100700, 1000)):
            with (
                self.subTest(mode=mode, uid=uid),
                patch.object(maintenance.os, "geteuid", return_value=1000),
                patch.object(Path, "resolve", lambda self, strict=True: self),
                patch.object(
                    Path,
                    "lstat",
                    return_value=SimpleNamespace(st_mode=mode, st_uid=uid),
                ),
            ):
                with self.assertRaises(RuntimeError):
                    scope.validate()

    def test_materializer_QA_host_bind_keeps_fixed_container_path_and_caps(self):
        scope = Scope(RUN)
        owner = install_resources.Installer(
            {"runtime_image": IMAGE, "source_sha256": "3" * 64},
            {"materialize": b"public"},
            scope=scope,
        )
        with (
            patch.object(owner, "command", return_value=b"4" * 64) as commands,
            patch.object(owner, "inspect", return_value="4" * 64),
        ):
            owner.create("materialize")
        args = commands.call_args.args
        self.assertIn("--label=io.aqua.qa-run=" + RUN, args)
        self.assertIn("--label=io.aqua.run=" + owner.name, args)
        self.assertIn(
            "--mount=type=bind,src="
            + str(scope.private)
            + ",dst="
            + str(PRODUCTION_PRIVATE),
            args,
        )
        self.assertFalse(
            any("src=" + str(PRODUCTION_PRIVATE) in argument for argument in args)
        )
        self.assertIn("--cap-drop=ALL", args)
        self.assertIn("--network=none", args)

    def test_capture_and_recovery_all_QA_host_mounts_socket_owned(self):
        scope = Scope(RUN)
        values = {
            "runtime_image": IMAGE,
            "source_sha256": "3" * 64,
            "code_manifest_sha256": "4" * 64,
        }
        for owner, role in (
            (export_resources.Owned(values, scope=scope), "peer"),
            (export_resources.Owned(values, scope=scope), "dump"),
            (recover.Recovery(values, "public", scope=scope), "recovery"),
        ):
            with (
                self.subTest(role=role),
                patch.object(owner, "command", return_value=b"5" * 64) as commands,
                patch.object(owner, "inspect", return_value="5" * 64),
            ):
                owner.create(role)
                args = commands.call_args.args
                self.assertIn("--label=io.aqua.qa-run=" + RUN, args)
                self.assertIn("--label=io.aqua.run=" + owner.name, args)
                mounts = [arg for arg in args if arg.startswith("--mount=")]
                self.assertTrue(
                    all(
                        str(scope.parent) in mount
                        or "src=" + scope.socket + "," in mount
                        for mount in mounts
                    )
                )
                self.assertTrue(all(mount.endswith(",readonly") for mount in mounts))
                self.assertFalse(
                    any(
                        "aqua_app_sockets" in argument
                        or "src=/home/ben2004/.aqua-runtime" in argument
                        for argument in args
                    )
                )

    def test_stopped_QA_checks_actual_owned_ID_labels_and_state(self):
        scope = Scope(RUN)
        schedule = ("no scheduler installed for " + RUN + "\n").encode()
        value = {
            "backend_id": "b" * 64,
            "backend_image": IMAGE,
            "database_id": "d" * 64,
            "database_image": "sha256:" + "e" * 64,
            "paused_cron_sha256": hashlib.sha256(schedule).hexdigest(),
        }
        calls = []

        def run(args, maximum=16384):
            self.assertEqual(maximum, 16384)
            calls.append(args)
            if "ps" in args:
                return (
                    value["backend_id"].encode()
                    if "label=io.aqua.role=stopped-backend" in args
                    else b""
                )
            if "inspect" in args:
                if value["backend_id"] in args:
                    values = [value["backend_id"], IMAGE, False, 0, ""]
                elif any("Config.Labels" in arg for arg in args):
                    values = ["/" + RUN + "-pg", {"io.aqua.run": RUN}]
                else:
                    values = [value["database_id"], value["database_image"], True]
                return b"\n".join(json.dumps(item).encode() for item in values)
            if "exec" in args:
                return b"9\n"
            raise AssertionError("unexpected host operation")

        with (
            patch.object(maintenance, "run", side_effect=run),
            patch.object(maintenance, "read", return_value=schedule),
        ):
            maintenance.stopped(value, 9, scope)
        self.assertTrue(any("label=io.aqua.run=" + RUN in call for call in calls))
        self.assertFalse(
            any(any("compose.project=bank-ai" in arg for arg in call) for call in calls)
        )
        self.assertTrue(
            all(value["database_id"] in call for call in calls if "exec" in call)
        )


if __name__ == "__main__":
    unittest.main()
