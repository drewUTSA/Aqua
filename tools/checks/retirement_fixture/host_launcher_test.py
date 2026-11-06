"""Private publisher scheduling/ownership/source guards; all Docker is fake."""

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

from host_adapter_test import host, config

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.resolve().parents[2] / "ops/retirement"))
spec = importlib.util.spec_from_file_location(
    "private_publisher_launcher",
    HERE.resolve().parents[2] / "ops/retirement/publisher_launcher.py",
)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def test_default_and_pending_execute_do_not_read_keys_or_call_docker(self):
        result = subprocess.run(
            [
                sys.executable,
                "-E",
                "-s",
                "-B",
                str(HERE.resolve().parents[2] / "ops/retirement/publisher_launcher.py"),
            ],
            capture_output=True,
            check=True,
            timeout=3,
        )
        self.assertEqual(
            json.loads(result.stdout),
            {
                "status": "prepared_only",
                "production_enabled": False,
                "secret_reads": 0,
                "Docker_actions": 0,
            },
        )
        with (
            patch.object(
                launcher, "directory", side_effect=AssertionError("path read")
            ),
            patch.object(launcher, "Docker", side_effect=AssertionError("Docker")),
        ):
            self.assertEqual(launcher.launch(), "disabled")

    def test_invalid_host_deadlines_reject_before_private_or_pool_io(self):
        with (
            patch.object(host.time, "monotonic", return_value=100),
            patch.object(
                host, "read_private", side_effect=AssertionError("key/config read")
            ),
            patch.object(host, "pool_for", side_effect=AssertionError("pool")),
        ):
            for deadline in (True, float("nan"), float("inf"), 99, 100, 156, "150"):
                with (
                    self.subTest(deadline=repr(deadline)),
                    self.assertRaises(host.HostUnavailable),
                ):
                    host.execute(deadline=deadline)

    def test_earlier_inherited_deadline_timer_precedes_io_and_pool_close_is_bounded(
        self,
    ):
        events = []
        fake_signal = SimpleNamespace(
            SIGALRM=14,
            ITIMER_REAL=0,
            signal=lambda *a: "previous",
            setitimer=lambda *a: events.append(("timer", a[1])),
        )
        pool = SimpleNamespace(
            open=lambda **k: events.append(("open", k)),
            close=lambda **k: events.append(("close", k)),
        )
        publisher = SimpleNamespace(startup=lambda: events.append(("startup", None)))

        def read(*a):
            self.assertEqual(events[0], ("timer", 40))
            return json.dumps(config()).encode()

        with (
            patch.object(host.time, "monotonic", return_value=100),
            patch.object(host, "signal", fake_signal),
            patch.object(host, "read_private", side_effect=read),
            patch.object(host, "signing_key", return_value=object()),
            patch.object(host, "ProtectedFile", return_value=object()),
            patch.object(host, "pool_for", return_value=pool),
            patch.object(host, "HostPublisher", return_value=publisher),
            patch.object(
                host, "tick_loop", return_value={"status": "idle", "steps": 40}
            ) as tick,
        ):
            self.assertEqual(
                host.execute(deadline=140), {"status": "idle", "steps": 40}
            )
            self.assertEqual(tick.call_args.kwargs["deadline"], 140)
        self.assertEqual(events[-2:], [("close", {"timeout": 1}), ("timer", 0)])

    def test_docker_work_and_cleanup_share_50_and55_second_deadlines(self):
        now = [0.0]
        with patch.object(launcher.time, "monotonic", side_effect=lambda: now[0]):
            docker = launcher.Docker()

            def call(*a, **k):
                self.assertEqual(k["env"], launcher.COMMAND_ENV)
                return SimpleNamespace(returncode=0, stdout=b"fixed", stderr=b"")

            with patch.object(launcher.subprocess, "run", side_effect=call) as invoke:
                now[0] = 49.5
                self.assertEqual(docker.call("metadata", timeout=8), "fixed")
                self.assertEqual(invoke.call_args.kwargs["timeout"], 0.5)
                now[0] = 51
                with self.assertRaises(launcher.Unavailable):
                    docker.call("work")
                docker.call("cleanup", cleanup=True, timeout=8)
                self.assertEqual(invoke.call_args.kwargs["timeout"], 4)
                now[0] = 55
                with self.assertRaises(launcher.Unavailable):
                    docker.call("cleanup", cleanup=True)

    def test_foreign_name_nonce_purpose_or_identifier_cannot_be_removed(self):
        identifier = "a" * 64
        for name, purpose, nonce in (
            ("/foreign", launcher.PURPOSE, "owned"),
            ("/" + launcher.NAME, "foreign", "owned"),
            ("/" + launcher.NAME, launcher.PURPOSE, "foreign"),
        ):
            docker = launcher.Docker()
            calls = []
            docker.ids = lambda *a, **k: [identifier]

            def call(*a, **k):
                calls.append(a)
                return (
                    identifier
                    + "\n"
                    + name
                    + "\n"
                    + json.dumps({"io.aqua.purpose": purpose, "io.aqua.run": nonce})
                )

            docker.call = call
            self.assertFalse(docker.clean("owned", identifier))
            self.assertFalse(any(a[:2] == ("container", "rm") for a in calls))
        docker = launcher.Docker()
        docker.owned = lambda *a, **k: "b" * 64
        docker.call = lambda *a, **k: self.fail("foreign identifier removal")
        self.assertFalse(docker.clean("owned", identifier))

    def test_ambiguous_create_cannot_be_reported_as_proven_absence(self):
        docker = launcher.Docker()
        docker.owned = lambda *a, **k: None
        docker.ids = lambda *a, **k: []
        self.assertFalse(docker.clean("owned", None))
        self.assertTrue(docker.clean("owned", "a" * 64))
        docker.ids = lambda *a, **k: ["a" * 64]
        self.assertFalse(docker.clean("owned", "a" * 64))

    @unittest.skipUnless(
        os.name == "posix", "actual UID1000 FD/mode/source byte checks"
    )
    def test_verified_module_bytes_survive_later_source_replacement(self):
        self.assertEqual(os.getuid(), 1000)
        with tempfile.TemporaryDirectory(prefix=".host-code-", dir=HERE) as folder:
            root = Path(folder).resolve()
            root.chmod(0o700)
            files = {
                name: b"from retirement.fingerprints import MARKER\n"
                for name in launcher.FILES
            }
            files["backend-sources/retirement/fingerprints.py"] = b"MARKER='verified'\n"
            files["host-sources/retirement_host.py"] = (
                b"from retirement.fingerprints import MARKER\nprint(json.dumps({'marker':MARKER,'deadline_arg':sys.argv[-1]}))\n"
            )
            # The fixture entry needs only its own standard imports, no keys.
            files["host-sources/retirement_host.py"] = (
                b"import json,sys\n" + files["host-sources/retirement_host.py"]
            )
            for name, raw in files.items():
                path = root / name
                path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                path.parent.chmod(0o700)
                path.write_bytes(raw)
                path.chmod(0o600)
            manifest = json.dumps(
                {n: hashlib.sha256(b).hexdigest() for n, b in files.items()}
            ).encode()
            (root / "code-manifest.json").write_bytes(manifest)
            (root / "code-manifest.json").chmod(0o600)
            code = launcher.VERIFY_CODE.replace(
                "root=Path('/publisher')", "root=Path(" + repr(str(root)) + ")"
            )
            code = code.replace(
                "# Import ONLY",
                "(root/'backend-sources/retirement/fingerprints.py').write_text(\"MARKER='replaced'\\n\")\n# Import ONLY",
                1,
            )
            saved = {
                n: m
                for n, m in sys.modules.items()
                if n == "retirement" or n.startswith("retirement.")
            }
            captured = io.StringIO()
            try:
                with (
                    patch.object(
                        sys,
                        "argv",
                        ["verify", hashlib.sha256(manifest).hexdigest(), "123.5"],
                    ),
                    redirect_stdout(captured),
                ):
                    exec(compile(code, "fixed_verified_sources", "exec"), {})
                self.assertEqual(
                    json.loads(captured.getvalue()),
                    {"marker": "verified", "deadline_arg": "123.5"},
                )
            finally:
                for name in list(sys.modules):
                    if name == "retirement" or name.startswith("retirement."):
                        del sys.modules[name]
                sys.modules.update(saved)


if __name__ == "__main__":
    unittest.main()
