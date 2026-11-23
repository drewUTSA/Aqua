"""Regression coverage for portable setup, model selection and scoped cleanup."""

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import zipfile

import build
import model_cache
import run


class PresenterTests(unittest.TestCase):
    def test_bundle_contains_canonical_bootstrap_and_every_runtime_module(self):
        with tempfile.TemporaryDirectory() as temp:
            first, second = (Path(temp) / name for name in ("first.zip", "second.zip"))
            build.build(first)
            build.build(second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as component:
                self.assertEqual(
                    set(component.namelist()), {*build.FILES, "bootstrap.psql"}
                )
                self.assertEqual(
                    component.read("bootstrap.psql"),
                    (
                        build.HERE.parents[1] / "backend/migrations/bootstrap.psql"
                    ).read_bytes().replace(b"\r\n", b"\n"),
                )

    def test_cleanup_selects_the_matching_label_and_only_expected_roles(self):
        session = "a" * 24
        lines = (
            f"aqua-presenter-{session}-api abc\naqua-presenter-else-pg def\nother xyz\n"
        )
        response = subprocess.CompletedProcess([], 0, stdout=lines.encode())
        with mock.patch.object(run, "docker", return_value=response) as docker:
            run.cleanup(session)
            self.assertIn(
                "label=" + run.LABEL + "=" + session, docker.call_args_list[0].args
            )
            self.assertEqual(
                docker.call_args_list[1:],
                [mock.call("rm", "--force", "--volumes", "abc")],
            )
            with self.assertRaises(ValueError):
                run.cleanup("*")
            self.assertEqual(docker.call_count, 2)

    def test_engine_timeout_is_retried_during_readiness(self):
        with mock.patch.object(
            run,
            "docker",
            side_effect=[
                subprocess.TimeoutExpired("docker", 12),
                subprocess.CompletedProcess([], 0),
            ],
        ) as command:
            run.wait_command("local", ["ready"])
        self.assertEqual(command.call_count, 2)

    def test_cleanup_continues_after_a_failed_removal(self):
        session = "b" * 24
        listed = subprocess.CompletedProcess(
            [],
            0,
            stdout=f"aqua-presenter-{session}-api abc\naqua-presenter-{session}-pg def\n".encode(),
        )
        with mock.patch.object(
            run, "docker", side_effect=[listed, RuntimeError("busy"), None]
        ) as command:
            with self.assertRaisesRegex(RuntimeError, "api"):
                run.cleanup(session)
        self.assertEqual(
            command.call_args_list[-1], mock.call("rm", "--force", "--volumes", "def")
        )

    def test_manual_cleanup_preserves_an_active_session(self):
        with (
            mock.patch.object(
                run, "remove_profile", side_effect=run.ActiveProfile("open")
            ),
            mock.patch.object(run, "cleanup") as cleanup,
        ):
            with self.assertRaises(run.ActiveProfile):
                run.recover("c" * 24)
            cleanup.assert_not_called()
        with (
            mock.patch.object(run, "remove_profile"),
            mock.patch.object(run, "cleanup") as cleanup,
        ):
            run.recover("c" * 24)
            cleanup.assert_called_once_with("c" * 24)

    def test_mounts_include_only_pinned_read_only_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = b"test model"
            digest = hashlib.sha256(payload).hexdigest()
            blob = root / "blobs" / ("sha256-" + digest)
            blob.parent.mkdir()
            blob.write_bytes(payload)
            (blob.parent / "unrelated").write_bytes(b"private")
            manifest = root / model_cache.MANIFEST
            manifest.parent.mkdir(parents=True)
            raw = json.dumps(
                {
                    "config": {"digest": "sha256:" + digest, "size": len(payload)},
                    "layers": [],
                }
            ).encode()
            manifest.write_bytes(raw)
            with mock.patch.object(
                model_cache, "DIGEST", hashlib.sha256(raw).hexdigest()
            ):
                args = model_cache.verified_mounts(root)
                self.assertEqual(args[::2], ["--mount", "--mount"])
                self.assertTrue(all(v.endswith(",readonly") for v in args[1::2]))
                self.assertFalse(any("unrelated" in v for v in args))
                blob.write_bytes(b"bad model!")
                with self.assertRaises(ValueError):
                    model_cache.verified_mounts(root)
            with self.assertRaises(ValueError):
                model_cache.verified_mounts(root)

    def test_changed_transfer_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "synthetic.zip"
            archive.write_bytes(b"old")
            original = {
                archive.name: {"bytes": 3, "sha256": hashlib.sha256(b"old").hexdigest()}
            }
            run.require_archive(archive, original)
            archive.write_bytes(b"new")
            with self.assertRaises(ValueError):
                run.require_archive(archive, original)


if __name__ == "__main__":
    unittest.main()
