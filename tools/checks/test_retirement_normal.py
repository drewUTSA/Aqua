"""Normal-startup orchestration scope/identity guards, no Docker or private reads."""

import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
import unittest

import retirement_normal_resources as resources
import run_retirement_normal as runner
from retirement_normal_image import IMAGE, RUNTIME_FILES, MANIFEST_SHA256

ROOT = Path(__file__).resolve().parents[2]
RUN = "aqua-retirement-host-" + "1" * 24


class NormalGuards(unittest.TestCase):
    def fresh(self):
        return resources.NormalResources(RUN, IMAGE, b"public source")

    def test_defaults_start_no_server_or_pool(self):
        for name in (
            "tools/checks/run_retirement_normal.py",
            "tools/checks/retirement_fixture/normal_recover.py",
        ):
            with self.subTest(name=name):
                result = subprocess.run(
                    [sys.executable, str(ROOT / name)],
                    capture_output=True,
                    timeout=5,
                    check=True,
                )
                value = json.loads(result.stdout)
                self.assertEqual(value["status"], "prepared_only")
                self.assertEqual(value.get("Docker_actions", 0), 0)
                self.assertEqual(value.get("private_reads", 0), 0)
                self.assertEqual(value.get("pool_opens", 0), 0)

    def test_exact_compiled_runtime_subset_is_public_and_root_pinned(self):
        additions = {
            "nl2sql/retrieval/graph.py",
            "nl2sql/retrieval/query.py",
            "auth/google_redirect.py",
            "auth/google_redirect_bridge.py",
            "auth/google_redirect_protocol.py",
        }
        self.assertTrue(additions <= RUNTIME_FILES.keys())
        self.assertEqual(len(RUNTIME_FILES.keys() - additions), 191)
        self.assertEqual(len(RUNTIME_FILES), 196)
        self.assertEqual(len(MANIFEST_SHA256), 64)
        self.assertEqual(IMAGE, runner.IMAGE)
        self.assertIn("main.py", RUNTIME_FILES)
        self.assertIn("retirement/runtime.py", RUNTIME_FILES)
        self.assertIn("migrations/0009_retirement_deletion.sql", RUNTIME_FILES)
        self.assertTrue(
            all(
                not name.startswith("/") and ".." not in Path(name).parts
                for name in RUNTIME_FILES
            )
        )

    def test_all_five_roles_refuse_before_flag_barrier(self):
        owner = self.fresh()
        with patch.object(resources.commands, "docker") as docker:
            for role in resources.ROLES:
                with self.subTest(role=role), self.assertRaises(RuntimeError):
                    owner.create(role)
            docker.assert_not_called()
            self.assertEqual(owner.attempted, [])

    def test_every_role_has_only_owned_RO_sources_socket_no_installed_keys(self):
        for role in resources.ROLES:
            owner = self.fresh()
            owner.append_ready = True
            with (
                self.subTest(role=role),
                patch.object(owner, "verify_layout"),
                patch.object(
                    resources.commands, "docker", return_value=b"a" * 64
                ) as docker,
                patch.object(owner, "inspect", return_value="a" * 64),
            ):
                owner.create(role)
                args = docker.call_args.args
                self.assertIn("--network=none", args)
                self.assertIn("--read-only", args)
                self.assertIn("--cap-drop=ALL", args)
                self.assertIn("--memory=1g", args)
                self.assertIn("--cpus=1", args)
                self.assertFalse(
                    any(
                        value.startswith(("--cap-add", "--publish", "--pid="))
                        for value in args
                    )
                )
                mounts = [value for value in args if value.startswith("--mount=")]
                self.assertEqual(len(mounts), 5)
                self.assertTrue(all(value.endswith(",readonly") for value in mounts))
                self.assertTrue(
                    all(
                        str(owner.root) in value or "src=" + owner.volume + "," in value
                        for value in mounts
                    )
                )
                self.assertFalse(
                    any(
                        "aqua_app_sockets" in value
                        or "/home/ben2004/.aqua-runtime" in value
                        or "signing.key" in value
                        or "recovery.dsn" in value
                        or "docker.sock" in value
                        for value in mounts
                    )
                )
                pythonpath = next(
                    value for value in args if value.startswith("--env=PYTHONPATH=")
                )
                self.assertTrue(pythonpath.startswith("--env=PYTHONPATH=/app:"))
                self.assertNotIn("/checks/backend:", pythonpath)
                self.assertEqual(owner.created[role], "a" * 64)

    def test_known_ID_retained_before_first_inspection_failure(self):
        for role in resources.ROLES:
            owner = self.fresh()
            owner.append_ready = True

            def inspect(selected):
                self.assertEqual(owner.created[selected], "a" * 64)
                raise RuntimeError("inspection lost")

            with (
                self.subTest(role=role),
                patch.object(owner, "verify_layout"),
                patch.object(resources.commands, "docker", return_value=b"a" * 64),
                patch.object(owner, "inspect", side_effect=inspect),
            ):
                with self.assertRaises(RuntimeError):
                    owner.create(role)
                self.assertIn(role, owner.uncertain)

    def test_renamed_role_and_unresolved_lost_create_remain_red(self):
        owner = self.fresh()
        owner.created["normal-purge"] = "a" * 64
        with (
            patch.object(owner, "inspect", return_value=None),
            patch.object(
                resources.commands, "docker", return_value=b"a" * 64
            ) as docker,
        ):
            self.assertFalse(owner.remove("normal-purge"))
            self.assertEqual(docker.call_args.args[0], "ps")
        owner.created.clear()
        with (
            patch.object(owner, "inspect", return_value=None),
            patch.object(resources.commands, "docker") as docker,
        ):
            self.assertFalse(owner.remove("normal-purge"))
            docker.assert_not_called()

    def test_PG_control_uses_current_inspected_retained_ID_only(self):
        owner = self.fresh()
        owner.created["pg"] = "a" * 64
        with patch.object(owner, "inspect", return_value="a" * 64):
            self.assertEqual(runner.pg(owner), "a" * 64)
        for observed in (None, "b" * 64):
            with (
                self.subTest(observed=observed),
                patch.object(owner, "inspect", return_value=observed),
                self.assertRaises(RuntimeError),
            ):
                runner.pg(owner)


if __name__ == "__main__":
    unittest.main()
