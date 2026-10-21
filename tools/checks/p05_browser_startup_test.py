"""Offline regressions for the temporary Postgres initdb readiness race."""

import subprocess
import unittest
from unittest.mock import patch

import p05_browser_resources as resources

RUN = "aqua-p05-browser-" + "a" * 24
PG = "b" * 64
PROCESS = ("exec", PG, "cat", "/proc/1/comm")
SOCKET = ("exec", PG, "pg_isready", "-h", "/run/aqua-app-db", "-U", "postgres")


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class StartupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.addCleanup(patch.stopall)
        patch.object(resources.time, "monotonic", self.clock.monotonic).start()
        patch.object(resources.time, "sleep", self.clock.sleep).start()

    def test_socket_ready_during_initdb_cannot_accept_temporary_server(self) -> None:
        processes = iter([b"bash\n", b"", b"postgres\n"])
        observed = []

        def docker(*args: str, **kwargs: object) -> bytes:
            observed.append(args)
            # The temporary socket would claim readiness if incorrectly checked.
            return next(processes) if args == PROCESS else b"accepting connections"

        with patch.object(resources, "docker", side_effect=docker):
            resources.wait_for_postgres(PG)
        self.assertEqual(observed, [PROCESS, PROCESS, PROCESS, SOCKET])
        self.assertEqual(self.clock.now, 1.0)

    def test_final_postmaster_and_private_socket_are_both_required(self) -> None:
        with patch.object(
            resources, "docker", side_effect=[b"postgres\n", b"accepting connections"]
        ) as operation:
            resources.wait_for_postgres(PG)
        self.assertEqual(
            [call.args for call in operation.call_args_list], [PROCESS, SOCKET]
        )
        self.assertEqual(self.clock.now, 0)

    def test_transient_restart_failure_recovers_before_sql(self) -> None:
        for failure in (
            RuntimeError("fixture_docker_operation_failed"),
            subprocess.TimeoutExpired("docker", 5),
        ):
            with self.subTest(error=type(failure).__name__):
                self.clock.now = 0
                with patch.object(
                    resources,
                    "docker",
                    side_effect=[b"postgres\n", failure, b"postgres\n", b"ready"],
                ) as operation:
                    resources.wait_for_postgres(PG)
                self.assertEqual(
                    [call.args for call in operation.call_args_list],
                    [PROCESS, SOCKET, PROCESS, SOCKET],
                )
                self.assertEqual(self.clock.now, 0.5)

    def test_stuck_entrypoint_or_empty_identity_times_out_without_socket(self) -> None:
        for identity in (b"bash\n", b"", b"postgres-other\n"):
            with self.subTest(identity=identity):
                self.clock.now = 0
                with patch.object(
                    resources, "docker", return_value=identity
                ) as operation:
                    with self.assertRaisesRegex(
                        RuntimeError, "fixture_postgres_unavailable"
                    ):
                        resources.wait_for_postgres(PG)
                self.assertEqual(self.clock.now, 45)
                self.assertEqual(operation.call_count, 90)
                self.assertTrue(
                    all(call.args == PROCESS for call in operation.call_args_list)
                )

    def test_final_postmaster_with_unavailable_socket_still_times_out(self) -> None:
        def docker(*args: str, **kwargs: object) -> bytes:
            if args == PROCESS:
                return b"postgres\n"
            raise RuntimeError("fixture_docker_operation_failed")

        with patch.object(resources, "docker", side_effect=docker):
            with self.assertRaisesRegex(RuntimeError, "fixture_postgres_unavailable"):
                resources.wait_for_postgres(PG)
        self.assertEqual(self.clock.now, 45)

    def test_slow_commands_use_remaining_deadline_and_cannot_pass_late(self) -> None:
        def docker(*args: str, **kwargs: object) -> bytes:
            if args == PROCESS:
                self.clock.now += 44.8
                return b"postgres\n"
            self.assertLessEqual(kwargs["timeout"], 0.21)
            self.clock.now += 0.3
            return b"accepting connections"

        with patch.object(resources, "docker", side_effect=docker) as operation:
            with self.assertRaisesRegex(RuntimeError, "fixture_postgres_unavailable"):
                resources.wait_for_postgres(PG)
        self.assertEqual(operation.call_count, 2)

    def test_failed_readiness_prevents_role_bootstrap_and_worker_creation(self) -> None:
        def docker(*args: str, **kwargs: object) -> bytes:
            return (
                ("sha256:" + PG).encode() if args[:2] == ("image", "inspect") else b""
            )

        fixture = resources.Resources(RUN)
        with (
            patch.object(resources, "docker", side_effect=docker) as operation,
            patch.object(resources, "create", return_value=PG) as create,
            patch.object(resources, "initialize") as initialize,
            patch.object(
                resources,
                "wait_for_postgres",
                side_effect=RuntimeError("fixture_postgres_unavailable"),
            ) as readiness,
        ):
            with self.assertRaisesRegex(RuntimeError, "fixture_postgres_unavailable"):
                fixture.provision("fixture", {})
        readiness.assert_called_once_with(PG)
        initialize.assert_not_called()
        self.assertEqual(create.call_count, 1)
        self.assertFalse(any("psql" in call.args for call in operation.call_args_list))


if __name__ == "__main__":
    unittest.main()
