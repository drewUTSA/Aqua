"""Closed packaging and resource-ownership gates for the frozen replay runner."""

import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import run_ai_replay as runner

IMAGE = "sha256:" + "a" * 64


class ReplayRunnerTests(unittest.TestCase):
    def test_archive_adds_only_the_named_fixture_not_arbitrary_jsonl(self):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w"):
            pass
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / "tools/checks/fixtures/ai_replay_dataset.jsonl"
            fixture.parent.mkdir(parents=True)
            fixture.write_bytes(b'{"synthetic":true}\n')
            (fixture.parent / "private.jsonl").write_text("must not package")
            (root / ".env").write_text("must not package")
            with (
                patch.object(runner, "ROOT", root),
                patch.object(runner, "FIXTURE", fixture),
                patch.object(runner, "source_archive", return_value=stream.getvalue()),
            ):
                archive, digest = runner.replay_archive()
            with tarfile.open(fileobj=io.BytesIO(archive)) as contents:
                self.assertEqual(
                    contents.getnames(),
                    ["tools/checks/fixtures/ai_replay_dataset.jsonl"],
                )
                self.assertEqual(
                    contents.extractfile(contents.getnames()[0]).read(),
                    fixture.read_bytes(),
                )
            self.assertEqual(len(digest), 64)

    def test_existing_output_and_image_tags_fail_before_docker_work(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing.json"
            output.write_text("preserve")
            with patch.object(
                runner, "docker", side_effect=AssertionError("Docker must not run")
            ):
                with self.assertRaises(FileExistsError):
                    runner.run(IMAGE, output)
                with self.assertRaises(ValueError):
                    runner.run("aqua-runtime:latest", Path(directory) / "new.json")
            self.assertEqual(output.read_text(), "preserve")

    def test_output_inside_source_is_denied_before_docker_work(self):
        with patch.object(
            runner, "docker", side_effect=AssertionError("Docker must not run")
        ):
            with self.assertRaises(ValueError):
                runner.run(IMAGE, runner.ROOT / ".check-results/forbidden.json")

    def test_partial_provision_removes_exact_ids_and_cleanup_failure_stays_failed(self):
        for absent in (True, False):
            with (
                self.subTest(absent=absent),
                tempfile.TemporaryDirectory() as directory,
            ):
                removed = []

                def docker(*args, **kwargs):
                    if args[0] == "image":
                        return IMAGE.encode()
                    self.assertEqual(args, ("rm", "--force", "exact-owned-id"))
                    removed.append(args[-1])
                    return b""

                def provision(**kwargs):
                    kwargs["containers"].append("exact-owned-id")
                    raise RuntimeError("synthetic setup failure")

                inspection = subprocess.CompletedProcess(
                    [], 1 if absent else 0, b"", b"No such container" if absent else b""
                )
                output = Path(directory) / "report.json"
                with (
                    patch.object(runner, "docker", docker),
                    patch.object(
                        runner, "replay_archive", return_value=(b"source", "digest")
                    ),
                    patch.object(runner, "provision_core", provision),
                    patch.object(runner.subprocess, "run", return_value=inspection),
                ):
                    self.assertEqual(runner.run(IMAGE, output), 1)
                report = json.loads(output.read_text())
                self.assertEqual(removed, ["exact-owned-id"])
                self.assertEqual(report["status"], "failed")
                self.assertEqual(
                    report["remaining_ids"], [] if absent else ["exact-owned-id"]
                )
                self.assertEqual(
                    report["cleanup"],
                    "removed_and_absence_confirmed" if absent else "failed",
                )


if __name__ == "__main__":
    unittest.main()
