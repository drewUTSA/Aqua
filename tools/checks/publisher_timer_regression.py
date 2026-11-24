"""Stdlib-only tests of actual publisher timer AST; no key/SQL/Docker imports."""

import ast
import json
import math
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HOST_SOURCE = Path(__file__).resolve().parents[2] / "ops/retirement/retirement_host.py"
CONSTANTS = {"MAX_SECONDS": 55, "MAX_STEPS": 55, "CADENCE": 1.0}


def load_host(source=HOST_SOURCE):
    """Compile only current source nodes; never copy function bodies or import it."""
    selected = []
    found = set()
    for node in ast.parse(source.read_bytes(), filename=str(source)).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in CONSTANTS:
                if (
                    target.id in found
                    or ast.literal_eval(node.value) != CONSTANTS[target.id]
                ):
                    raise AssertionError("publisher_timer_constant_changed")
                found.add(target.id)
                selected.append(node)
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in {
            "HostUnavailable",
            "tick_loop",
            "execute",
        }:
            if node.name in found:
                raise AssertionError("publisher_timer_definition_duplicated")
            found.add(node.name)
            selected.append(node)
    if found != set(CONSTANTS) | {"HostUnavailable", "tick_loop", "execute"}:
        raise AssertionError("publisher_timer_source_inventory_changed")
    namespace = {
        "__name__": "publisher_timer_ast_under_test",
        "math": math,
        "time": time,
        "signal": signal,
        "HOST_DIRECTORY": Path("/synthetic-host"),
        "CHECKPOINT_DIRECTORY": Path("/synthetic-checkpoint"),
    }
    exec(
        compile(ast.Module(body=selected, type_ignores=[]), str(source), "exec"),
        namespace,
    )
    return namespace


def fake_dependencies(host, events, *, startup=lambda: None, close=lambda **_: None):
    settings = SimpleNamespace(
        witness=None,
        public_key=b"synthetic",
        installation="synthetic",
        key_id="synthetic",
        commitment=b"synthetic",
    )
    pool = SimpleNamespace(
        open=lambda **_: events.append("pool_model_open"), close=close
    )
    host.update(
        {
            "read_private": lambda *a, **k: events.append("private_model")
            or b"synthetic",
            "parse_settings": lambda *_: settings,
            "signing_key": lambda *_: object(),
            "ProtectedFile": lambda *a, **k: object(),
            "pool_for": lambda *_: pool,
            "HostPublisher": lambda *_: SimpleNamespace(
                startup=startup, once=lambda: events.append("tick_model")
            ),
        }
    )


class PublisherTimerModelTests(unittest.TestCase):
    def test_malformed_reserve_denied_before_first_tick(self):
        host = load_host(HOST_SOURCE)
        for reserve in (
            None,
            True,
            False,
            "2",
            -1,
            2.001,
            float("nan"),
            float("inf"),
            float("-inf"),
        ):
            with (
                self.subTest(reserve=repr(reserve)),
                self.assertRaises(host["HostUnavailable"]),
            ):
                host["tick_loop"](
                    SimpleNamespace(
                        once=lambda: self.fail("invalid reserve reached publisher")
                    ),
                    deadline=55,
                    clock=lambda: 0,
                    cleanup_reserve=reserve,
                )

    def test_exact_two_second_reserve_preserves_original_cadence(self):
        host, now, calls = load_host(HOST_SOURCE), [0.0], []

        def once():
            calls.append(now[0])
            now[0] += 0.1
            return object()

        def sleep(seconds):
            self.assertGreater(seconds, 0)
            self.assertLessEqual(seconds, 1)
            now[0] += seconds

        result = host["tick_loop"](
            SimpleNamespace(once=once),
            deadline=55,
            clock=lambda: now[0],
            sleep=sleep,
            cleanup_reserve=2,
        )
        self.assertEqual(result, {"status": "checked", "steps": 53})
        self.assertEqual(now[0], 53)
        for left, right in zip(calls, calls[1:]):
            self.assertAlmostEqual(right - left, 1)

    def test_startup_consuming_cleanup_reserve_denies_without_tick(self):
        host = load_host(HOST_SOURCE)
        for now in (53.0, 54.0, 54.9):
            with self.subTest(now=now), self.assertRaises(host["HostUnavailable"]):
                host["tick_loop"](
                    SimpleNamespace(
                        once=lambda: self.fail("late startup reached publisher")
                    ),
                    deadline=55,
                    clock=lambda: now,
                    cleanup_reserve=2,
                )

    def execute_model(self, startup_time):
        host, now, events = load_host(HOST_SOURCE), [100.0], []
        timer_events = []
        fake_signal = SimpleNamespace(
            SIGALRM=14,
            ITIMER_REAL=0,
            signal=lambda *a: "previous",
            setitimer=lambda *a: timer_events.append(a[1]),
        )

        def startup():
            now[0] = startup_time

        def close(**kwargs):
            self.assertEqual(kwargs, {"timeout": 1})
            self.assertEqual(timer_events, [40])
            events.append("close_entered")
            now[0] += 1

        fake_dependencies(host, events, startup=startup, close=close)
        real_loop = host["tick_loop"]

        def sleep(seconds):
            now[0] += seconds

        host["tick_loop"] = lambda publisher, **kw: real_loop(
            publisher, **kw, clock=lambda: now[0], sleep=sleep
        )
        host["signal"] = fake_signal
        with patch.object(time, "monotonic", lambda: now[0]):
            result = None
            try:
                result = host["execute"](deadline=140)
            except host["HostUnavailable"]:
                events.append("unavailable")
        self.assertEqual(timer_events, [40, 0])
        return result, now[0], events

    def test_late_startup_fails_closed_and_bounded_close_still_runs(self):
        result, now, events = self.execute_model(138.0)
        self.assertIsNone(result)
        self.assertEqual(now, 139)
        self.assertNotIn("tick_model", events)
        self.assertIn("close_entered", events)
        self.assertIn("unavailable", events)

    def test_just_enough_startup_keeps_inherited_deadline_and_closes(self):
        result, now, events = self.execute_model(137.9)
        self.assertEqual(result, {"status": "idle", "steps": 1})
        self.assertEqual(now, 139)
        self.assertEqual(events.count("tick_model"), 1)
        self.assertIn("close_entered", events)
        self.assertNotIn("unavailable", events)


def actual_alarm(source, mode):
    """Child-only actual POSIX timer. Every external/private dependency is fake."""
    host, events = load_host(source), []

    def startup():
        events.append("startup_model")
        if mode == "late-startup":
            time.sleep(1.6)

    def close(**kwargs):
        if kwargs != {"timeout": 1}:
            raise AssertionError("close_budget_changed")
        events.append("close_entered")
        time.sleep(3 if mode == "slow-close" else 0.05)
        events.append("close_finished")

    fake_dependencies(host, events, startup=startup, close=close)
    previous = signal.getsignal(signal.SIGALRM)
    started = time.monotonic()
    try:
        result = host["execute"](deadline=started + 2.5)
        category = "returned"
    except host["HostUnavailable"]:
        result, category = None, "HostUnavailable"
    restored = signal.getsignal(signal.SIGALRM) == previous
    cleared = signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
    if not restored or not cleared:
        raise AssertionError("timer_cleanup_changed")
    return {
        "category": category,
        "result": result,
        "elapsed_seconds": time.monotonic() - started,
        "events": events,
        "timer_cancelled_handler_restored": True,
        "private_IO_Docker_SQL_network": False,
    }


class PublisherTimerRealAlarmTests(unittest.TestCase):
    def probe(self, mode):
        completed = subprocess.run(
            [
                sys.executable,
                "-E",
                "-s",
                "-B",
                str(Path(__file__).resolve()),
                "--actual-alarm",
                str(HOST_SOURCE),
                mode,
            ],
            capture_output=True,
            timeout=6,
            check=True,
        )
        self.assertEqual(completed.stderr, b"")
        self.assertLessEqual(len(completed.stdout), 8192)
        value = json.loads(completed.stdout)
        self.assertIs(value["timer_cancelled_handler_restored"], True)
        self.assertIs(value["private_IO_Docker_SQL_network"], False)
        return value

    def test_real_alarm_ordinary_completion_finishes_pool_close(self):
        value = self.probe("normal")
        self.assertEqual(value["category"], "returned")
        self.assertEqual(value["result"], {"status": "idle", "steps": 1})
        self.assertIn("close_finished", value["events"])
        self.assertLess(value["elapsed_seconds"], 2.5)

    def test_real_alarm_slow_close_still_fails_inside_original_hard_timer(self):
        value = self.probe("slow-close")
        self.assertEqual(value["category"], "HostUnavailable")
        self.assertIn("close_entered", value["events"])
        self.assertNotIn("close_finished", value["events"])
        self.assertLess(value["elapsed_seconds"], 3)

    def test_real_alarm_late_startup_rejects_before_any_tick_and_closes(self):
        value = self.probe("late-startup")
        self.assertEqual(value["category"], "HostUnavailable")
        self.assertNotIn("tick_model", value["events"])
        self.assertIn("close_finished", value["events"])
        self.assertLess(value["elapsed_seconds"], 2.5)


if __name__ == "__main__":
    if (
        len(sys.argv) == 4
        and sys.argv[1] == "--actual-alarm"
        and sys.argv[3] in {"normal", "slow-close", "late-startup"}
    ):
        try:
            print(
                json.dumps(actual_alarm(Path(sys.argv[2]), sys.argv[3]), sort_keys=True)
            )
        except BaseException:
            print('{"status":"failed","category":"publisher_timer_probe_failed"}')
            raise SystemExit(1) from None
    else:
        unittest.main()
