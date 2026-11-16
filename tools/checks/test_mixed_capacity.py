"""Offline guards for the fixed workload's scope, metrics and resource ledger."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mixed_capacity_contract import LIMITS, Meter, distribution, route_label
import mixed_capacity_runner as runner
import mixed_capacity_docker as local_docker


class MixedCapacity(unittest.TestCase):
    def test_sparse_timings_do_not_claim_tail_percentiles_and_invalid_samples_fail(
        self,
    ):
        self.assertEqual(
            distribution([3, 1, 2]), {"samples": 3, "p50_ms": 2, "max_ms": 3}
        )
        result = distribution(list(range(1, 33)))
        self.assertEqual((result["p50_ms"], result["p95_ms"]), (16, 31))
        self.assertNotIn("p99_ms", result)
        for values in ([], [-1], [float("nan")], [float("inf")]):
            with self.assertRaises(ValueError):
                distribution(values)

    def test_workload_cannot_choose_external_urls_extra_routes_or_mutations(self):
        for method, path in (
            ("GET", "https://aqua-ai.us/api/v1/me"),
            ("PATCH", "/api/v1/me"),
            ("POST", "/api/v1/companion/help"),
            ("GET", "/api/v1/chats?limit=10000"),
            ("GET", "/api/v1/analysis-requests/../events"),
        ):
            with self.assertRaises(ValueError):
                route_label(method, path)
        self.assertEqual(route_label("GET", "/api/v1/chats?limit=20"), "history")

    def test_concurrent_and_total_http_overload_are_rejected_without_extra_reservations(
        self,
    ):
        meter, entered, release = Meter(), threading.Barrier(7), threading.Event()

        def hold():
            meter.reserve()
            entered.wait(timeout=2)
            self.assertTrue(release.wait(2))
            meter.finish("history", 200, 1, 1)

        with ThreadPoolExecutor(max_workers=6) as workers:
            held = [workers.submit(hold) for _ in range(6)]
            entered.wait(timeout=2)
            try:
                with self.assertRaises(ValueError):
                    meter.reserve()
                self.assertEqual(meter.requests, 6)
            finally:
                release.set()
            for item in held:
                item.result(timeout=2)
        for _ in range(LIMITS["http_requests"] - 6):
            meter.reserve()
            meter.finish("history", 200, 1, 1)
        with self.assertRaises(ValueError):
            meter.reserve()
        self.assertEqual(meter.report()["requests"], 200)

    def test_existing_output_is_preserved_before_docker_or_fixture_action(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "existing.json"
            path.write_text("preserve")
            with patch.object(runner.run_backend, "docker") as docker:
                with self.assertRaises(ValueError):
                    runner.run_mixed("sha256:" + "a" * 64, path)
                docker.assert_not_called()
            self.assertEqual(path.read_text(), "preserve")

    def test_cleanup_refuses_replaced_ids_images_and_foreign_labels(self):
        name, expected = "aqua-p12-mixed-" + "a" * 24 + "-tests", "sha256:" + "b" * 64
        base = ["c" * 64, "/" + name, expected, "p00-checks"]
        for index, replacement in (
            (0, "d" * 64),
            (2, "sha256:" + "d" * 64),
            (3, "another-purpose"),
        ):
            row = list(base)
            row[index] = replacement
            reply = subprocess.CompletedProcess(
                [], 0, " ".join(map(json.dumps, row)).encode(), b""
            )
            transport = SimpleNamespace(capture=lambda *args, **kwargs: reply)
            with self.assertRaises(ValueError):
                runner.owned(name, expected, base[0], 1, transport)

    def test_windows_and_linux_local_daemons_are_verified_then_pinned_for_every_operation(
        self,
    ):
        for platform, (binary, context, endpoint) in local_docker.SPECS.items():
            transport = local_docker.LocalDocker(
                platform=platform,
                environ={
                    "HOME": "/fixture",
                    "DOCKER_CONTEXT": context,
                    "PRIVATE_CANARY": "do-not-copy",
                },
            )
            metadata = [
                {
                    "Name": context,
                    "Endpoints": {"docker": {"Host": endpoint, "SkipTLSVerify": False}},
                    "TLSMaterial": {},
                }
            ]
            replies = [
                subprocess.CompletedProcess([], 0, context.encode() + b"\n", b""),
                subprocess.CompletedProcess([], 0, json.dumps(metadata).encode(), b""),
                subprocess.CompletedProcess([], 0, b"fixed-local-reply", b""),
            ]
            with patch.object(
                local_docker.subprocess, "run", side_effect=replies
            ) as command:
                transport.verify(time.monotonic() + 5)
                self.assertEqual(
                    transport.execute(
                        "container", "inspect", "fixture-owned", timeout=1
                    ),
                    b"fixed-local-reply",
                )
            operation = command.call_args
            self.assertEqual(
                operation.args[0][:4], [binary, "--host", endpoint, "--tls=false"]
            )
            self.assertNotIn("DOCKER_CONTEXT", operation.kwargs["env"])
            self.assertNotIn("PRIVATE_CANARY", operation.kwargs["env"])
            self.assertFalse(set(operation.kwargs["env"]) & local_docker.OVERRIDES)

    def test_remote_context_and_environment_transport_overrides_are_denied_before_commands(
        self,
    ):
        with patch.object(local_docker.subprocess, "run") as command:
            for platform in local_docker.SPECS:
                for key in local_docker.OVERRIDES:
                    with self.assertRaises(ValueError):
                        local_docker.LocalDocker(
                            platform=platform, environ={key: "override"}
                        )
                with self.assertRaises(ValueError):
                    local_docker.LocalDocker(
                        platform=platform, environ={"DOCKER_CONTEXT": "aqua-codex"}
                    )
            command.assert_not_called()

    def test_context_endpoint_spoofing_and_unverified_cleanup_transport_fail_closed(
        self,
    ):
        for endpoint in (
            "ssh://aqua-codex",
            "tcp://127.0.0.1:2375",
            "unix:///tmp/other.sock",
        ):
            transport = local_docker.LocalDocker(platform="linux", environ={})
            with self.assertRaises(ValueError):
                transport.capture("rm", "--force", "fixture-owned")
            metadata = [
                {
                    "Name": "default",
                    "Endpoints": {"docker": {"Host": endpoint, "SkipTLSVerify": False}},
                    "TLSMaterial": {},
                }
            ]
            replies = [
                subprocess.CompletedProcess([], 0, b"default\n", b""),
                subprocess.CompletedProcess([], 0, json.dumps(metadata).encode(), b""),
            ]
            with patch.object(
                local_docker.subprocess, "run", side_effect=replies
            ) as command:
                with self.assertRaises(ValueError):
                    transport.verify(time.monotonic() + 5)
                with self.assertRaises(ValueError):
                    transport.capture("container", "inspect", "fixture-owned")
                self.assertEqual(command.call_count, 2)


if __name__ == "__main__":
    unittest.main()
