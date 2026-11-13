"""Closed owned-fixture native129 orchestration guards; no Docker actions."""

import json
from pathlib import Path
import signal
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import retirement_capture_resources as resources
import run_retirement_capture as runner

ROOT = Path(__file__).resolve().parents[2]
RUN = "aqua-retirement-host-" + "a" * 24
IMAGE = "sha256:" + "b" * 64


class CaptureGuards(unittest.TestCase):
    def fresh(self):
        return resources.CaptureResources(
            RUN, IMAGE, b"public reviewed setter", "c" * 64
        )

    def test_default_invocation_has_zero_actions(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/checks/run_retirement_capture.py")],
            capture_output=True,
            timeout=5,
            check=True,
        )
        self.assertEqual(
            json.loads(result.stdout),
            {"status": "prepared_only", "Docker_actions": 0, "writes": 0},
        )

    def test_no_capture_process_before_append_barrier(self):
        owner = self.fresh()
        with patch.object(resources.commands, "docker") as docker:
            with self.assertRaises(RuntimeError):
                owner.create("capture")
            docker.assert_not_called()
            self.assertEqual(owner.attempted, [])

    def test_capture_uses_owned_paths_only_and_actual_compiled_image(self):
        owner = self.fresh()
        owner.append_ready = True
        with (
            patch.object(owner, "verify_layout"),
            patch.object(
                resources.commands, "docker", return_value=b"d" * 64
            ) as docker,
            patch.object(owner, "inspect", return_value="d" * 64),
        ):
            self.assertEqual(owner.create("capture"), "d" * 64)
        args = docker.call_args.args
        self.assertIn("--network=none", args)
        self.assertIn("--read-only", args)
        self.assertIn("--cap-drop=ALL", args)
        self.assertIn("--memory=1g", args)
        self.assertIn("--memory-swap=1g", args)
        self.assertIn("--cpus=1", args)
        self.assertFalse(
            any(
                argument.startswith(("--cap-add", "--publish", "--pid="))
                for argument in args
            )
        )
        mounts = [argument for argument in args if argument.startswith("--mount=")]
        self.assertEqual(len(mounts), 4)
        self.assertTrue(all(argument.endswith(",readonly") for argument in mounts))
        self.assertTrue(
            all(
                str(owner.root) in argument or "src=" + owner.volume + "," in argument
                for argument in mounts
            )
        )
        self.assertFalse(
            any(
                "aqua_app_sockets" in argument
                or "/home/ben2004/.aqua-runtime" in argument
                or "compose" in argument
                for argument in args
            )
        )
        self.assertIn(
            "--env=PYTHONPATH=/app:/checks:/checks/tools/checks/retirement_fixture",
            args,
        )
        self.assertFalse(
            any("PYTHONPATH=/checks/backend" in argument for argument in args)
        )
        self.assertIn(IMAGE, args)
        self.assertEqual(owner.capture_id, "d" * 64)

    def test_valid_returned_capture_ID_is_retained_before_inspection_failure(self):
        owner = self.fresh()
        owner.append_ready = True

        def inspect(role):
            self.assertEqual(owner.capture_id, "d" * 64)
            raise RuntimeError("inspection lost")

        with (
            patch.object(owner, "verify_layout"),
            patch.object(resources.commands, "docker", return_value=b"d" * 64),
            patch.object(owner, "inspect", side_effect=inspect),
        ):
            with self.assertRaises(RuntimeError):
                owner.create("capture")
        self.assertEqual(owner.capture_id, "d" * 64)
        self.assertIn("capture", owner.uncertain)

    def test_renamed_capture_remains_unclean_without_blind_removal(self):
        owner = self.fresh()
        owner.capture_id = "d" * 64
        with (
            patch.object(owner, "inspect", return_value=None),
            patch.object(
                resources.commands, "docker", return_value=b"d" * 64
            ) as docker,
        ):
            self.assertFalse(owner.remove("capture"))
            self.assertEqual(docker.call_args.args[0], "ps")

    def test_original_capture_ID_and_name_both_absent_before_clean(self):
        owner = self.fresh()
        owner.capture_id = "d" * 64
        with (
            patch.object(owner, "inspect", return_value=None),
            patch.object(resources.commands, "docker", return_value=b"") as docker,
        ):
            self.assertTrue(owner.remove("capture"))
            self.assertIn("--filter=id=" + "d" * 64, docker.call_args.args)
        owner.capture_id = None
        with (
            patch.object(owner, "inspect", return_value=None),
            patch.object(resources.commands, "docker") as docker,
        ):
            self.assertFalse(owner.remove("capture"))
            docker.assert_not_called()

    def test_cleanup_retries_new_clear_role_after_failed_flag_operation(self):
        events = []

        class Node:
            def __truediv__(self, name):
                return self

            def exists(self):
                return True

            def unlink(self):
                raise AssertionError("failed flag operation cannot delete inode")

            def rmdir(self):
                raise AssertionError("failed flag operation cannot delete directory")

        class Owner:
            root = Node()
            attempted = ["capture", "set"]
            volume_attempted = True

            def remove(self, role):
                events.append(role)
                return True

            def remove_socket(self):
                events.append("socket")
                return True

        owner = Owner()
        report = {}

        def flag(instance, mode):
            self.assertEqual(mode, "clear")
            instance.attempted.append("clear")
            raise RuntimeError("lost clear start")

        with (
            patch.object(runner, "flag", side_effect=flag),
            patch.object(runner, "states", return_value=[]),
        ):
            runner.cleanup(owner, [], report, [], SimpleNamespace(cleaning=False))
        self.assertIn("clear", events)
        self.assertEqual(events[-1], "socket")
        self.assertIs(report["cleanup"], False)
        self.assertIn("append_flag_cleanup", report["remaining_resources"])

    def test_alarm_cancellation_is_controlled_and_latched_during_cleanup(self):
        with runner.Cancellation() as cancellation, runner.WorkAlarm(cancellation):
            with self.assertRaises(RuntimeError):
                cancellation.receive(signal.SIGALRM, None)
            cancellation.cleaning = True
            cancellation.receive(signal.SIGALRM, None)
        self.assertEqual(signal.alarm(0), 0)


class BaseOwnedIdentityGuards(unittest.TestCase):
    def fresh(self):
        return resources.Resources(RUN, IMAGE, b"public reviewed setter")

    def test_every_base_role_remembers_returned_ID_before_first_inspection(self):
        for role in ("pg", "initialize", "set", "publish0", "clear"):
            owner = self.fresh()
            owner.append_ready = role not in {"set"}
            owner.initializer_finished = True
            with (
                self.subTest(role=role),
                patch.object(owner, "verify_layout"),
                patch.object(resources.commands, "docker", return_value=b"d" * 64),
                patch.object(
                    owner, "inspect", side_effect=RuntimeError("inspect lost")
                ),
            ):
                if role in {"set", "clear"}:
                    owner.layout = {"authority": (1, 2)}
                with self.assertRaisesRegex(RuntimeError, "inspect lost"):
                    owner.create(role)
                self.assertEqual(owner.created[role], "d" * 64)
                self.assertIn(role, owner.uncertain)

    def test_renamed_owned_PG_never_becomes_cleanup_success(self):
        owner = self.fresh()

        def docker(*args, **kwargs):
            if args[0] == "create" or args[0] == "ps":
                return b"d" * 64
            raise AssertionError("must not remove unvalidated renamed container")

        with (
            patch.object(owner, "verify_layout"),
            patch.object(resources.commands, "docker", side_effect=docker),
            patch.object(owner, "inspect", side_effect=["d" * 64, None, None]),
        ):
            owner.create("pg")
            self.assertFalse(owner.remove("pg"))

    def test_unresolved_lost_create_absence_is_red(self):
        owner = self.fresh()
        owner.attempted = ["pg"]
        owner.uncertain = {"pg"}
        with (
            patch.object(owner, "inspect", return_value=None),
            patch.object(resources.commands, "docker") as docker,
        ):
            self.assertFalse(owner.remove("pg"))
            docker.assert_not_called()

    def test_lost_create_resolves_only_matching_metadata_then_dual_absence(self):
        owner = self.fresh()
        owner.attempted = ["pg"]
        owner.uncertain = {"pg"}
        meta = SimpleNamespace(
            returncode=0,
            stdout=b"\n".join(
                json.dumps(value).encode()
                for value in (
                    "d" * 64,
                    "/" + RUN + "-pg",
                    {"io.aqua.run": RUN, "io.aqua.purpose": resources.PURPOSE},
                )
            ),
            stderr=b"",
        )
        absent = SimpleNamespace(
            returncode=1,
            stdout=b"",
            stderr=("Error: No such container: " + RUN + "-pg\n").encode(),
        )
        import retirement_host_resources as base

        with (
            patch.object(base.subprocess, "run", side_effect=[meta, absent]),
            patch.object(base.commands, "docker", return_value=b"") as docker,
        ):
            self.assertTrue(owner.remove("pg"))
            self.assertEqual(owner.created["pg"], "d" * 64)
            self.assertEqual(docker.call_args_list[0].args, ("rm", "--force", "d" * 64))
            self.assertEqual(
                docker.call_args_list[1].args,
                (
                    "ps",
                    "--all",
                    "--no-trunc",
                    "--filter=id=" + "d" * 64,
                    "--format={{.ID}}",
                ),
            )

    def test_foreign_ID_cannot_replace_known_owned_name(self):
        owner = self.fresh()
        owner.created["pg"] = "d" * 64
        meta = SimpleNamespace(
            returncode=0,
            stdout=b"\n".join(
                json.dumps(value).encode()
                for value in (
                    "e" * 64,
                    "/" + RUN + "-pg",
                    {"io.aqua.run": RUN, "io.aqua.purpose": resources.PURPOSE},
                )
            ),
            stderr=b"",
        )
        import retirement_host_resources as base

        with (
            patch.object(base.subprocess, "run", return_value=meta),
            patch.object(base.commands, "docker") as docker,
        ):
            with self.assertRaises(RuntimeError):
                owner.remove("pg")
            docker.assert_not_called()

    def test_dump_executes_only_the_inspected_retained_ID(self):
        owner = SimpleNamespace(created={"pg": "d" * 64}, inspect=lambda role: "d" * 64)
        report = {}
        with patch.object(
            runner.commands, "docker", return_value=b"PGDMPsynthetic"
        ) as docker:
            self.assertEqual(
                runner.full_dump(owner, "publicfixture", report), b"PGDMPsynthetic"
            )
            self.assertEqual(docker.call_args.args[:3], ("exec", "-i", "d" * 64))
            self.assertEqual(docker.call_args.kwargs["data"], b"publicfixture\n")
        for observed in (None, "e" * 64):
            owner.inspect = lambda role: observed
            with (
                self.subTest(observed=observed),
                patch.object(runner.commands, "docker") as docker,
            ):
                with self.assertRaises(RuntimeError):
                    runner.full_dump(owner, "publicfixture", {})
                docker.assert_not_called()


class MissingInspectFormattingGuards(unittest.TestCase):
    def test_actual_single_newline_is_empty_only_with_exact_owned_NoSuch_error(self):
        import retirement_host_resources as base
        from ops.retirement.export_resources import Owned

        fixtures = (
            (base.Resources(RUN, IMAGE, b"public"), "pg", base),
            (
                resources.CaptureResources(RUN, IMAGE, b"public", "a" * 64),
                "capture",
                resources,
            ),
            (
                Owned({"runtime_image": IMAGE}),
                "peer",
                __import__("ops.retirement.export_resources", fromlist=["subprocess"]),
            ),
        )
        for owner, role, module in fixtures:
            name = (owner.run if hasattr(owner, "run") else owner.name) + "-" + role
            for stdout, stderr, accepted in (
                (
                    b"\n",
                    (
                        "Error response from daemon: No such container: " + name + "\n"
                    ).encode(),
                    True,
                ),
                (
                    b"garbage",
                    (
                        "Error response from daemon: No such container: " + name + "\n"
                    ).encode(),
                    False,
                ),
                (
                    b"\n\n",
                    (
                        "Error response from daemon: No such container: " + name + "\n"
                    ).encode(),
                    False,
                ),
                (
                    b"\n",
                    b"Error response from daemon: No such container: foreign\n",
                    False,
                ),
                (b"\n", b"permission denied\n", False),
            ):
                with (
                    self.subTest(role=role, stdout=stdout, stderr=stderr),
                    patch.object(
                        module.subprocess,
                        "run",
                        return_value=SimpleNamespace(
                            returncode=1, stdout=stdout, stderr=stderr
                        ),
                    ),
                ):
                    if accepted:
                        self.assertIsNone(owner.inspect(role))
                    else:
                        with self.assertRaises(RuntimeError):
                            owner.inspect(role)


class CaptureDeadlineGuards(unittest.TestCase):
    def producer(self):
        import importlib.util

        path = ROOT / "tools/checks/retirement_fixture/capture129.py"
        spec = importlib.util.spec_from_file_location("capture_phase_qa", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_existing_prep_alarm_is_rejected_until_explicit_phase_transition(self):
        from ops.retirement.operator_deadline import deadline

        producer = self.producer()
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))
        signal.alarm(20)
        try:
            with self.assertRaisesRegex(RuntimeError, "deadline_context_invalid"):
                with deadline():
                    pass

            def actual_capture():
                self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))
                with deadline():
                    self.assertGreater(signal.getitimer(signal.ITIMER_REAL)[0], 119)
                return "actual_production_deadline_entered"

            self.assertEqual(
                producer.capture_phase(actual_capture),
                "actual_production_deadline_entered",
            )
            self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))
        finally:
            signal.alarm(0)

    def test_failure_frame_emits_only_closed_category_never_private_message(self):
        producer = self.producer()
        self.assertEqual(
            producer.failure(
                RuntimeError("retirement_operator_deadline_context_invalid")
            ),
            "CAPTURE129_ERROR RuntimeError:retirement_operator_deadline_context_invalid",
        )
        value = producer.failure(RuntimeError("private password=never-print-this"))
        self.assertEqual(value, "CAPTURE129_ERROR RuntimeError:unclassified")
        self.assertNotIn("password", value)


if __name__ == "__main__":
    unittest.main()
