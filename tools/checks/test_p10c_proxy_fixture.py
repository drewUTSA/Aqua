"""Offline routing guards; real nginx behavior remains a separate required run."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import unquote

import p10c_proxy_probe as identity
import run_proxy


class IdentityProxyFixture(unittest.TestCase):
    def exercise(self, selected):
        transferred = []
        saved = []
        config, output = Path("/synthetic/nginx.conf"), Path("/synthetic/report.json")
        original_read = Path.read_bytes

        def read(path):
            return (
                b"# Synthetic offline configuration\n"
                if path == config
                else original_read(path)
            )

        def write(path, value, **_):
            self.assertEqual(path, output)
            saved.append(value)
            return len(value)

        def docker(*args, data=None, **_):
            if args[:2] == ("image", "inspect"):
                return ("sha256:" + "a" * 64 + "\n").encode()
            if args[0] == "stats":
                return b'{"Name":"synthetic"}\n'
            if args[0] == "exec" and "tee" in args:
                if args[-1] == "/tmp/proxy_probe.py":
                    transferred.append(data)
                return b""
            if args[0] == "exec" and "python" in args:
                return json.dumps(
                    {"mode": "blue_retest", "status": "passed", "requests": 64}
                ).encode()
            return b""

        with (
            patch.object(Path, "read_bytes", new=read),
            patch.object(Path, "write_text", new=write),
            patch.object(Path, "mkdir"),
            patch.object(run_proxy, "docker", side_effect=docker),
            patch.object(run_proxy, "create", side_effect=lambda name, *_a, **_k: name),
            patch.object(
                run_proxy.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=1, stderr=b"No such container"),
            ),
            redirect_stdout(io.StringIO()),
        ):
            result = run_proxy.run(config, output, identity_actions=selected)
        self.assertEqual(result, 0)
        self.assertEqual(len(saved), 1)
        report = json.loads(saved[0])
        self.assertEqual(report["cleanup"], "removed_and_absence_confirmed")
        self.assertEqual(report["remaining_ids"], [])
        self.assertEqual(len(transferred), 1)
        return transferred[0], report

    def test_ordinary_proxy_still_transfers_original_exercise(self):
        data, report = self.exercise(False)
        self.assertEqual(
            data, (run_proxy.ROOT / "tools/checks/proxy_probe.py").read_bytes()
        )
        self.assertNotIn("exercise_kind", report)

    def test_identity_flag_selects_only_the_fixed_additional_exercise(self):
        data, report = self.exercise(True)
        self.assertEqual(
            data, (run_proxy.ROOT / "tools/checks/p10c_proxy_probe.py").read_bytes()
        )
        self.assertEqual(report["exercise_kind"], "p10c_identity_actions")

    def test_identity_mode_rejects_baseline_before_any_operator_action(self):
        with (
            patch.object(run_proxy, "docker") as docker,
            patch.object(run_proxy, "create") as create,
        ):
            with self.assertRaisesRegex(ValueError, "no_unsafe_baseline"):
                run_proxy.run(
                    Path("unused"), Path("unused"), True, identity_actions=True
                )
            docker.assert_not_called()
            create.assert_not_called()

    def test_aliases_normalize_to_each_exact_cost_route(self):
        for path in (*identity.BOOTSTRAP, *(path for _, path in identity.PROOFS)):
            with self.subTest(path=path):
                variants = identity.aliases(path)
                self.assertEqual(len(set(variants)), 4)
                for variant in variants:
                    normalized = "/".join(
                        part for part in unquote(variant).split("/") if part
                    )
                    self.assertEqual("/" + normalized, path)

    def test_notifications_remain_outside_both_cost_families(self):
        paths = {*identity.BOOTSTRAP, *(path for _, path in identity.PROOFS)}
        self.assertNotIn("/api/v1/me/notification-settings", paths)
        self.assertEqual(len(paths), 10)


if __name__ == "__main__":
    unittest.main()
