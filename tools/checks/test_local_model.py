"""Offline broker/plan/provenance tests; SSH and Ollama are always stand-ins."""

import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import local_model_broker as broker
import local_model_remote as remote
import run_local_model as runner
import local_model_resources as resources


def body():
    return {
        "model": "qwen3:4b",
        "messages": [
            {"role": "system", "content": "synthetic rules"},
            {"role": "user", "content": "synthetic schema and question"},
        ],
        "stream": False,
        "think": False,
        "options": dict(remote.OPTIONS),
        "format": copy.deepcopy(remote.FORMAT),
    }


class LocalModelTests(unittest.TestCase):
    def test_default_plan_never_creates_resources_or_calls_ssh(self):
        with (
            patch.object(
                runner, "provision_model", side_effect=AssertionError("Docker")
            ),
            patch.object(broker.subprocess, "run", side_effect=AssertionError("SSH")),
            patch("sys.stdout", new_callable=io.StringIO) as output,
        ):
            self.assertEqual(runner.main([]), 0)
        plan = json.loads(output.getvalue())
        self.assertFalse(plan["execute"])
        self.assertFalse(plan["think"])

    def test_closed_body_rejects_host_model_options_prompt_and_unknown_fields(self):
        for attack in ("model", "think", "options", "oversize", "field", "role"):
            value = body()
            if attack == "model":
                value["model"] = "new-model"
            elif attack == "think":
                value["think"] = True
            elif attack == "options":
                value["options"]["num_predict"] = 99999
            elif attack == "oversize":
                value["messages"][1]["content"] = "x" * 65537
            elif attack == "field":
                value["host"] = "not-accepted"
            else:
                value["messages"][0]["role"] = "tool"
            with self.subTest(attack=attack), self.assertRaises(ValueError):
                remote.validate({"digest": "a" * 64, "body": value})

    def test_timeout_is_terminal_and_obeys_remaining_case_budget(self):
        instance = broker.Broker("a" * 64, time.monotonic() + 900)
        with patch.object(
            broker.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired("synthetic", 2),
        ) as call:
            with self.assertRaises(broker.BrokerStopped):
                instance.send(body(), time.monotonic() + 2)
            self.assertLessEqual(call.call_args.kwargs["timeout"], 2)
            self.assertTrue(instance.stopped and instance.remote_exit_unknown)
            with self.assertRaises(broker.BrokerStopped):
                instance.send(body(), time.monotonic() + 120)
            self.assertEqual(call.call_count, 1)

    def test_success_binds_response_model_completion_and_fixed_ssh_alias(self):
        raw = b'{"model":"qwen3:4b","done":true,"message":{"content":"synthetic"}}'
        response = json.dumps(
            {
                "status": "ok",
                "body": raw.decode(),
                "response_sha256": hashlib.sha256(raw).hexdigest(),
            }
        ).encode()
        instance = broker.Broker("a" * 64, time.monotonic() + 900)
        with patch.object(
            broker.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, response, b""),
        ) as call:
            self.assertEqual(instance.send(body(), time.monotonic() + 120), raw)
        args = call.call_args.args[0]
        self.assertIn("aqua-codex", args)
        self.assertIn("StrictHostKeyChecking=yes", args)
        self.assertNotIn("DATABASE_URL", call.call_args.kwargs["env"])
        if broker.os.name == "nt":
            self.assertEqual(
                set(call.call_args.kwargs["env"]), {"SystemRoot", "PROGRAMDATA"}
            )
        else:
            self.assertEqual(call.call_args.kwargs["env"], {})
        self.assertEqual(instance.calls, 1)
        self.assertEqual(
            instance.remote_sha256, hashlib.sha256(instance.source).hexdigest()
        )

    def test_call_cap_and_concurrency_refuse_before_ssh(self):
        for field, value in (("calls", 32), ("active", True), ("stopped", True)):
            instance = broker.Broker("a" * 64, time.monotonic() + 900)
            setattr(instance, field, value)
            with (
                patch.object(
                    broker.subprocess, "run", side_effect=AssertionError("SSH")
                ),
                self.assertRaises(broker.BrokerStopped),
            ):
                instance.send(body(), time.monotonic() + 120)

    def test_installed_digest_mismatch_never_posts_a_model_request(self):
        request = json.dumps({"digest": "a" * 64, "body": body()}).encode()
        fake_signal = SimpleNamespace(
            SIGALRM=14, signal=lambda *a: None, alarm=lambda *a: None
        )
        with (
            patch.object(remote, "signal", fake_signal),
            patch("sys.stdin", SimpleNamespace(buffer=io.BytesIO(request))),
            patch("sys.stdout", new_callable=io.StringIO) as output,
            patch.object(
                remote,
                "request_json",
                return_value=b'{"models":[{"name":"qwen3:4b","digest":"wrong"}]}',
            ) as network,
        ):
            remote.main()
        self.assertEqual(network.call_count, 1)
        self.assertEqual(network.call_args.args[:2], ("GET", "/api/tags"))
        self.assertEqual(
            json.loads(output.getvalue())["remote_physical_exit"], "not_submitted"
        )

    def test_fixed_pilot_holdout_selection_excludes_security_frozen_rank_cases(self):
        raw = (
            runner.ROOT / "tools/checks/fixtures/ai_replay_dataset.jsonl"
        ).read_bytes()
        pilot, heldout, digest = runner.selected_cases(raw)
        self.assertEqual((len(pilot), len(heldout)), (4, 24))
        self.assertTrue(all(c["split"] == "train" for c in pilot))
        self.assertTrue(
            all(c["split"] == "test" and c["kind"] == "answer" for c in heldout)
        )
        self.assertFalse({c["id"] for c in pilot} & {c["id"] for c in heldout})
        self.assertEqual(digest, hashlib.sha256(raw).hexdigest())

    def test_existing_receipt_is_preserved_before_any_docker_or_model_work(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing.json"
            output.write_text("preserve")
            with (
                patch.object(
                    runner, "provision_model", side_effect=AssertionError("Docker")
                ),
                self.assertRaises(FileExistsError),
            ):
                runner.run("sha256:" + "a" * 64, "b" * 64, output)
            self.assertEqual(output.read_text(), "preserve")

    def test_missing_images_fail_before_creation_and_never_download(self):
        with (
            patch.object(
                resources, "docker", side_effect=RuntimeError("missing image")
            ),
            patch.object(
                resources, "provision_core", side_effect=AssertionError("create")
            ),
        ):
            with self.assertRaises(RuntimeError):
                resources.provision_model(
                    "sha256:" + "a" * 64, "synthetic", [], b"source"
                )

    def test_remote_wrong_model_or_incomplete_reply_is_terminal(self):
        for changed in (
            {"model": "wrong", "done": True},
            {"model": "qwen3:4b", "done": False},
        ):
            raw = json.dumps(changed).encode()
            response = json.dumps(
                {
                    "status": "ok",
                    "body": raw.decode(),
                    "response_sha256": hashlib.sha256(raw).hexdigest(),
                }
            ).encode()
            instance = broker.Broker("a" * 64, time.monotonic() + 900)
            with (
                patch.object(
                    broker.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess([], 0, response, b""),
                ),
                self.assertRaises(broker.BrokerStopped),
            ):
                instance.send(body(), time.monotonic() + 120)
            self.assertTrue(instance.stopped and instance.remote_exit_unknown)

    def test_failed_attempt_is_recorded_and_future_cases_are_not_attempted(self):
        def failure(runner_id, case, instance, deadline):
            instance.calls += 1
            instance.remote_exit_unknown = True
            raise broker.BrokerStopped("synthetic timeout")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            with (
                patch.object(
                    runner, "provision_model", return_value="synthetic-runner"
                ),
                patch.object(
                    runner, "replay_archive", return_value=(b"source", "hash")
                ),
                patch.object(runner, "evaluate", side_effect=failure) as calls,
                patch("sys.stdout", new_callable=io.StringIO),
            ):
                self.assertEqual(runner.run("sha256:" + "a" * 64, "b" * 64, output), 1)
            report = json.loads(output.read_text())
            self.assertEqual(calls.call_count, 1)
            failed = [r for r in report["records"] if r["status"] == "case_failed"]
            self.assertEqual(len(failed), 1)
            self.assertEqual(failed[0]["provider_calls"], 1)
            self.assertEqual(report["remote_physical_exit"], "unknown")
            self.assertEqual(report["holdout"]["cases"], 24)
            self.assertEqual(
                sum(r["status"] == "not_completed" for r in report["records"]), 27
            )


if __name__ == "__main__":
    unittest.main()
