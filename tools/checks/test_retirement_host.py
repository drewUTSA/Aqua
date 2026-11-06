"""Offline denial and mount-scope checks before any native fixture execution."""

import json
from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import signal
import unittest
from unittest.mock import patch

import retirement_host_protocol as protocol
import retirement_host_resources as resources
import run_retirement_host as runner


class NativeFixtureGuards(unittest.TestCase):
    def test_preACK_pending_DTO_requires_literal_false_and_all_original_bindings(self):
        sys.path.insert(0, str(Path(runner.ROOT) / "tools/checks/retirement_fixture"))
        import native_support

        before = {
            "schemaVersion": 1,
            "user_id": "original-owner",
            "history_revision": "original-revision",
            "job": {
                "id": "original-job",
                "intent_id": "original-intent",
                "scope": "chat_history_v1",
                "state": "awaiting_authority",
                "accepted": False,
                "cleanup_complete": False,
                "created_at": "original-created",
                "receipt_expires_at": "original-fixed-expiry",
            },
        }
        native_support.pending_receipt(before, deepcopy(before))
        for key in ("user_id", "history_revision"):
            changed = deepcopy(before)
            changed[key] = "foreign"
            with self.subTest(field=key), self.assertRaises(AssertionError):
                native_support.pending_receipt(before, changed)
        for key in ("id", "intent_id", "scope", "created_at", "receipt_expires_at"):
            changed = deepcopy(before)
            changed["job"][key] = "foreign"
            with self.subTest(field=key), self.assertRaises(AssertionError):
                native_support.pending_receipt(before, changed)
        for key, value in (
            ("accepted", True),
            ("accepted", 0),
            ("cleanup_complete", True),
            ("cleanup_complete", 0),
            ("state", "complete"),
        ):
            changed = deepcopy(before)
            changed["job"][key] = value
            with (
                self.subTest(field=key, value=value),
                self.assertRaises(AssertionError),
            ):
                native_support.pending_receipt(before, changed)

    def test_outer_SIGTERM_runs_latched_cleanup_reaps_own_child_and_writes_red_report(
        self,
    ):
        program = r"""
import hashlib,json,os,pathlib,signal,subprocess,sys
from unittest.mock import patch
sys.path.insert(0,sys.argv[2])
import run_retirement_host as runner
root=pathlib.Path(sys.argv[1]);payload=b'public synthetic source';image='sha256:'+'a'*64
class Owned:
    attempted=['api'];volume_attempted=False;child=None
    def __init__(self):self.root=root/'owned';self.root.mkdir()
    def remove(self,role):
        assert role=='api'
        os.kill(os.getpid(),signal.SIGTERM) # A repeat must not interrupt cleanup.
        self.child.kill();self.child.wait(timeout=2)
        return True
owned=Owned()
def database(resources, source_root):
    owned.child=subprocess.Popen([sys.executable,'-c','import signal;signal.pause()'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    (root/'child.pid').write_text(str(owned.child.pid))
    os.kill(os.getpid(),signal.SIGTERM)
def docker(*args,**kwargs):
    assert args[:2]==('image','inspect')
    return image.encode()
with patch.object(runner,'BASE',root),patch.object(runner.sys,'platform','linux'),patch.object(runner.os,'geteuid',return_value=1000),patch.object(runner,'source',return_value=payload),patch.object(runner.commands,'docker',side_effect=docker),patch.object(runner,'Resources',return_value=owned),patch.object(runner,'running',return_value=[]),patch.object(runner,'states',return_value=[]),patch.object(runner,'directories'),patch.object(runner,'database',side_effect=database):
    code=runner.execute(image,hashlib.sha256(payload).hexdigest(),'aqua-retirement-host-'+'a'*24)
report=json.loads((owned.root/'report.json').read_text())
assert code==1 and report['status']=='failed' and report['cleanup'] and report['append_flags_never_set']
assert report['error'].startswith('Cancelled:') and owned.child.poll() is not None
print(json.dumps({'signal_cleanup':'passed','own_child_reaped':True,'Docker_subprocesses':0}))
"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            cleaned = False
            try:
                result = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        program,
                        str(root),
                        str(Path(runner.__file__).resolve().parent),
                    ],
                    capture_output=True,
                    timeout=8,
                )
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                value = json.loads(result.stdout.splitlines()[-1])
                self.assertEqual(
                    value,
                    {
                        "signal_cleanup": "passed",
                        "own_child_reaped": True,
                        "Docker_subprocesses": 0,
                    },
                )
                cleaned = True
            finally:
                if not cleaned and (root / "child.pid").exists():
                    try:
                        os.kill(int((root / "child.pid").read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_default_prepares_exact_source_without_Docker_or_writes(self):
        completed = subprocess.run(
            [sys.executable, str(Path(runner.__file__).resolve())],
            capture_output=True,
            timeout=5,
            check=True,
        )
        report = json.loads(completed.stdout)
        self.assertEqual(
            (report["status"], report["Docker_actions"], report["writes"]),
            ("prepared_only", 0, 0),
        )
        self.assertEqual(len(report["source_sha256"]), 64)

    def test_invalid_roles_images_and_run_names_never_reach_Docker(self):
        for name, image in (
            ("production", "sha256:" + "a" * 64),
            ("aqua-retirement-host-" + "b" * 24, "runtime:latest"),
        ):
            with patch.object(resources.commands, "docker") as docker:
                with self.assertRaises(ValueError):
                    resources.Resources(name, image, b"# captured setter")
            docker.assert_not_called()
        fixture = resources.Resources(
            "aqua-retirement-host-" + "b" * 24,
            "sha256:" + "a" * 64,
            b"# captured setter",
        )
        for role in ("../pg", "publish999", "other", "set;evil", "production-backend"):
            with self.assertRaises(ValueError):
                fixture.create(role)

    def test_role_mounts_caps_and_source_are_closed_and_readonly_where_required(self):
        with tempfile.TemporaryDirectory() as raw:
            fixture = resources.Resources(
                "aqua-retirement-host-" + "c" * 24,
                "sha256:" + "a" * 64,
                b"# captured setter",
            )
            fixture.root = Path(raw).resolve()
            for name in ("authority", "mail"):
                (fixture.root / name).mkdir()
            (fixture.root / "mail/physical.lock").touch(mode=0o600)
            info = (fixture.root / "authority").stat()
            fixture.layout = {"authority": (info.st_dev, info.st_ino)}
            for role in (
                "initialize",
                "set",
                "clear",
                "api",
                "publish0",
                "crash",
                "poison",
                "mail",
                "web0",
            ):
                with (
                    self.subTest(role=role),
                    patch.object(fixture, "admit"),
                    patch.object(fixture, "verify_layout"),
                    patch.object(fixture, "inspect", return_value="f" * 64),
                ):
                    with patch.object(
                        resources.commands, "docker", return_value=("f" * 64).encode()
                    ) as docker:
                        fixture.create(role)
                    args = docker.call_args.args
                    self.assertTrue(
                        all(
                            item in args
                            for item in (
                                "--network=none",
                                "--read-only",
                                "--cap-drop=ALL",
                                "--security-opt=no-new-privileges:true",
                            )
                        )
                    )
                    mounts = [item for item in args if item.startswith("--mount=")]
                    self.assertNotIn("docker.sock", " ".join(mounts))
                    caps = [item for item in args if item.startswith("--cap-add=")]
                    self.assertEqual(
                        caps,
                        (
                            [
                                "--cap-add=LINUX_IMMUTABLE",
                                "--cap-add=FOWNER",
                                "--cap-add=DAC_OVERRIDE",
                            ]
                            if role in {"set", "clear"}
                            else []
                        ),
                    )
                    if role in {"set", "clear"}:
                        self.assertEqual(len(mounts), 1)
                        self.assertIn("# captured setter", args)
                    if role == "api" or role.startswith("web") or role == "mail":
                        self.assertTrue(
                            all(item.endswith(",readonly") for item in mounts)
                        )
                    if role == "mail":
                        self.assertTrue(
                            any(
                                item.startswith("--env=ACCOUNT_MAIL_PHYSICAL_INODE=")
                                for item in args
                            )
                        )
                    self.assertNotIn("--privileged", args)

    def test_backend_termination_rejects_foreign_pid_role_application_before_Docker(
        self,
    ):
        fixture = SimpleNamespace(run="aqua-retirement-host-" + "d" * 24)
        for record, role in (
            ({"pid": "123", "application_name": fixture.run}, "aqua_app_runtime"),
            ({"pid": 123, "application_name": "other"}, "aqua_retirement_checkpoint"),
            ({"pid": 123, "application_name": fixture.run}, "postgres"),
        ):
            with patch.object(protocol.commands, "docker") as docker:
                with self.assertRaises(RuntimeError):
                    protocol.terminate_backend(fixture, record, role)
            docker.assert_not_called()
        with patch.object(protocol.commands, "docker", return_value=b"t\n") as docker:
            protocol.terminate_backend(
                fixture,
                {"pid": 123, "application_name": fixture.run},
                "aqua_retirement_checkpoint",
            )
        args = docker.call_args.args
        self.assertEqual(args[:2], ("exec", fixture.run + "-pg"))
        self.assertIn("pid=123 AND usename='aqua_retirement_checkpoint'", args[-1])
        self.assertIn("application_name='" + fixture.run + "'", args[-1])

    def test_native_flag_typo_cannot_fall_back_to_mocked_inode(self):
        sys.path.insert(0, str(Path(runner.ROOT) / "tools/checks/retirement_fixture"))
        import native_support

        for value in ("false", "TRUE", "1", ""):
            with patch.dict("os.environ", {native_support.FLAG: value}):
                with self.assertRaises(RuntimeError):
                    native_support.enabled()
        with patch.dict("os.environ", {native_support.FLAG: "true"}):
            self.assertTrue(native_support.enabled())

    def test_real_admission_and_pinned_directory_prevent_early_signer_and_substitution(
        self,
    ):
        fixture = resources.Resources(
            "aqua-retirement-host-" + "e" * 24,
            "sha256:" + "a" * 64,
            b"# captured setter",
        )
        for role in ("set", "api", "publish0", "crash", "poison", "mail"):
            with patch.object(resources.commands, "docker") as docker:
                with self.assertRaises(RuntimeError):
                    fixture.create(role)
            docker.assert_not_called()
        with tempfile.TemporaryDirectory() as raw:
            fixture.root = Path(raw).resolve()
            (fixture.root / "authority").mkdir()
            current = (fixture.root / "authority").stat()
            fixture.layout = {"authority": (current.st_dev, current.st_ino)}
            fixture.verify_layout()
            (fixture.root / "authority").rename(fixture.root / "replaced")
            (fixture.root / "authority").mkdir()
            with self.assertRaises(RuntimeError):
                fixture.verify_layout()


if __name__ == "__main__":
    unittest.main()
