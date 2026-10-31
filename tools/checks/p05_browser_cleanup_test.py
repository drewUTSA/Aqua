"""Offline regressions for ambiguous Docker results and fixture cleanup."""

import io
import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import p05_browser_docker as commands
import p05_browser_host as bridge
import p05_browser_resources as resources

RUN = "aqua-p05-browser-" + "a" * 24
ID = "b" * 64


class CleanupTests(unittest.TestCase):
    def test_volume_created_before_timeout_is_found_and_removed(self) -> None:
        fixture = resources.Resources(RUN)

        def docker(*args: str, **kwargs: object) -> bytes:
            if args[:2] == ("image", "inspect"):
                return ("sha256:" + ID).encode()
            if args[:2] == ("volume", "create"):
                raise subprocess.TimeoutExpired("docker", 60)
            return b""

        with patch.object(resources, "docker", side_effect=docker) as operation:
            with self.assertRaises(subprocess.TimeoutExpired):
                fixture.provision("fixture", {})
            with patch.object(
                resources, "owned_resource", side_effect=[fixture.volume, None]
            ):
                self.assertEqual(fixture.cleanup(), [])
        operation.assert_any_call("volume", "rm", fixture.volume, timeout=15)

    def test_container_created_before_timeout_is_found_by_owned_name(self) -> None:
        fixture = resources.Resources(RUN)

        def docker(*args: str, **kwargs: object) -> bytes:
            return (
                ("sha256:" + ID).encode() if args[:2] == ("image", "inspect") else b""
            )

        with patch.object(resources, "docker", side_effect=docker) as operation:
            with patch.object(
                resources, "create", side_effect=subprocess.TimeoutExpired("docker", 60)
            ):
                with self.assertRaises(subprocess.TimeoutExpired):
                    fixture.provision("fixture", {})
            with patch.object(
                resources,
                "owned_resource",
                side_effect=[ID, None, fixture.volume, None],
            ):
                self.assertEqual(fixture.cleanup(), [])
        operation.assert_any_call("rm", "--force", ID, timeout=15)
        self.assertIn(("container", RUN + "-pg"), fixture.attempted)

    def test_unresolved_timed_out_create_is_not_claimed_absent(self) -> None:
        fixture = resources.Resources(RUN)
        fixture.preparing("container", RUN + "-pg")
        with (
            patch.object(resources, "owned_resource", return_value=None),
            patch.object(resources, "docker") as remove,
        ):
            self.assertEqual(fixture.cleanup(), [RUN + "-pg"])
            remove.assert_not_called()

    def test_inspect_or_ownership_failure_does_not_delete(self) -> None:
        fixture = resources.Resources(RUN)
        fixture.preparing("volume", fixture.volume)
        with (
            patch.object(
                resources,
                "owned_resource",
                side_effect=RuntimeError("ownership_mismatch"),
            ),
            patch.object(resources, "docker") as remove,
        ):
            self.assertEqual(fixture.cleanup(), [fixture.volume])
            remove.assert_not_called()

    def test_lost_remove_response_checks_actual_absence(self) -> None:
        fixture = resources.Resources(RUN)
        fixture.preparing("container", RUN + "-pg")
        with (
            patch.object(resources, "owned_resource", side_effect=[ID, None]),
            patch.object(
                resources, "docker", side_effect=subprocess.TimeoutExpired("docker", 15)
            ),
        ):
            self.assertEqual(fixture.cleanup(), [])

    def test_exact_name_and_both_labels_required(self) -> None:
        labels = {"io.aqua.purpose": commands.PURPOSE, "io.aqua.run": RUN}
        for observed, observed_labels in [
            ("/unrelated", labels),
            ("/" + RUN + "-pg", {}),
            ("/" + RUN + "-pg", {**labels, "io.aqua.run": "another-run"}),
        ]:
            raw = b"\n".join(
                json.dumps(field).encode() for field in (ID, observed, observed_labels)
            )
            with patch.object(
                commands.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0, stdout=raw, stderr=b""),
            ):
                with self.assertRaises(RuntimeError):
                    commands.owned_resource("container", RUN + "-pg", RUN)
        raw = b"\n".join(
            json.dumps(field).encode() for field in (ID, "/" + RUN + "-pg", labels)
        )
        with patch.object(
            commands.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout=raw, stderr=b""),
        ):
            self.assertEqual(commands.owned_resource("container", RUN + "-pg", RUN), ID)

    def test_daemon_failure_is_not_no_such_resource(self) -> None:
        for error in (
            b"connect: no such file or directory",
            b"No such volume: unrelated",
        ):
            with patch.object(
                commands.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=1, stdout=b"", stderr=error),
            ):
                with self.assertRaises(RuntimeError):
                    commands.owned_resource("volume", RUN + "-socket", RUN)
        with patch.object(
            commands.subprocess,
            "run",
            return_value=SimpleNamespace(
                returncode=1,
                stdout=b"",
                stderr=(
                    "Error response from daemon: No such volume: " + RUN + "-socket\n"
                ).encode(),
            ),
        ):
            self.assertIsNone(commands.owned_resource("volume", RUN + "-socket", RUN))

    def test_out_of_scope_name_is_rejected_without_docker(self) -> None:
        with patch.object(commands.subprocess, "run") as operation:
            with self.assertRaises(ValueError):
                commands.owned_resource("container", "aqua-app-db", RUN)
            operation.assert_not_called()

    def test_docker29_volume_absence_requires_exact_name(self) -> None:
        for observed, absent in [(RUN + "-socket", True), ("unrelated", False)]:
            result = SimpleNamespace(
                returncode=1,
                stdout=b"\n",
                stderr=(
                    "Error response from daemon: get " + observed + ": no such volume\n"
                ).encode(),
            )
            with patch.object(commands.subprocess, "run", return_value=result):
                if absent:
                    self.assertIsNone(
                        commands.owned_resource("volume", RUN + "-socket", RUN)
                    )
                else:
                    with self.assertRaises(RuntimeError):
                        commands.owned_resource("volume", RUN + "-socket", RUN)

    def run_host(self, cleanup: list[str], wait: Mock) -> tuple[int, dict]:
        child = SimpleNamespace(
            stdin=Mock(),
            stdout=io.BytesIO(
                (
                    json.dumps(
                        {
                            "kind": "ready",
                            "schema_version": bridge.fixture_schema(bridge.ROOT),
                        }
                    )
                    + "\n"
                ).encode()
            ),
            wait=wait,
            terminate=Mock(),
            kill=Mock(),
        )
        child.stdin.close.side_effect = BrokenPipeError()
        owned = Mock()
        owned.provision.return_value = ID
        owned.cleanup.return_value = cleanup
        with (
            patch.object(bridge, "Resources", return_value=owned),
            patch.object(bridge.subprocess, "Popen", return_value=child),
            patch.object(
                bridge, "message", return_value={"id": "finished", "kind": "finish"}
            ),
            patch.object(bridge, "emit") as emitted,
            patch.multiple(
                bridge.signal,
                SIGALRM=14,
                SIGHUP=1,
                signal=Mock(),
                alarm=Mock(),
                create=True,
            ),
        ):
            result = bridge.host("http://127.0.0.1:5000", "fixture")
        owned.cleanup.assert_called_once()
        return result, emitted.call_args.args[0]

    def test_broken_pipe_close_still_cleans_and_reports(self) -> None:
        result, final = self.run_host([], Mock(return_value=0))
        self.assertEqual(result, 0)
        self.assertEqual(final["report"]["cleanup"], "removed_and_absence_confirmed")

    def test_remaining_resource_makes_final_report_fail(self) -> None:
        result, final = self.run_host([RUN + "-pg"], Mock(return_value=0))
        self.assertEqual(result, 1)
        self.assertEqual(final["status"], "failed")
        self.assertEqual(final["report"]["remaining_ids"], [RUN + "-pg"])

    def test_hung_worker_still_cleans_and_cannot_pass(self) -> None:
        result, final = self.run_host(
            [], Mock(side_effect=subprocess.TimeoutExpired("docker", 5))
        )
        self.assertEqual(result, 1)
        self.assertEqual(final["report"]["worker_exit"], "unconfirmed_or_nonzero")
        self.assertEqual(final["report"]["cleanup"], "removed_and_absence_confirmed")


if __name__ == "__main__":
    unittest.main()
