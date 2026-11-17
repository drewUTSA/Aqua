"""Fake-clock tests only; no alarms, private operations or native callbacks."""

import unittest
from dataclasses import FrozenInstanceError

from authority_budget import BudgetDenied, Deadline


class Clock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now


class InheritedDeadlineTests(unittest.TestCase):
    def budget(self, clock, **changes):
        values = {
            "install_started": 0.0,
            "owner_end": 300.0,
            "client_end": 300.0,
            "run_end": 300.0,
            "clock": clock,
        }
        return Deadline(**(values | changes))

    def test_minimum_original_install_owner_client_and_run_ends(self):
        clock = Clock(100)
        self.assertEqual(self.budget(clock).end, 180)
        for field in ("owner_end", "client_end", "run_end"):
            with self.subTest(field=field):
                self.assertEqual(self.budget(clock, **{field: 140}).end, 140)
        self.assertEqual(
            self.budget(clock, owner_end=170, client_end=160, run_end=150).end, 150
        )

    def test_an_alarm_or_owner_extension_cannot_reset_the_captured_end(self):
        clock = Clock(20)
        budget = self.budget(clock, owner_end=130)
        # Extending an external owner's/alarm's end cannot mutate this object.
        self.assertEqual(budget.end, 130)
        with self.assertRaises(FrozenInstanceError):
            budget.end = 320
        with self.assertRaises(FrozenInstanceError):
            budget.owner_end = 320
        clock.now = 131
        with self.assertRaises(BudgetDenied):
            budget.checkpoint()

    def test_capture_then_readback_spend_one_shared_budget(self):
        clock = Clock()
        budget = self.budget(clock)
        self.assertEqual(budget.seconds("head"), 20)
        clock.now = 10
        self.assertEqual(budget.seconds("encrypt"), 120)
        clock.now = 50
        self.assertEqual(budget.seconds("decrypt"), 120)
        clock.now = 80
        self.assertEqual(budget.seconds("sql_restore"), 97)
        clock.now = 150
        self.assertEqual(budget.seconds("decrypt"), 26)
        clock.now = 155
        with self.assertRaises(BudgetDenied):
            budget.seconds("sql_restore")
        self.assertEqual(budget.end, 180)

    def test_sql_admission_keeps_exact_original_greater_than_45_requirement(self):
        clock = Clock(131)
        budget = self.budget(clock)
        self.assertEqual(budget.seconds("sql_restore"), 46)
        clock.now = 132
        with self.assertRaises(BudgetDenied):
            budget.seconds("sql_restore")

    def test_cleanup_reserves_are_inside_parent_end_and_caps_never_grow(self):
        clock = Clock(160)
        budget = self.budget(clock)
        self.assertEqual(budget.seconds("head"), 16)
        self.assertEqual(budget.seconds("encrypt"), 12)
        self.assertEqual(budget.seconds("decrypt"), 16)
        self.assertEqual(budget.seconds("encrypt", requested=5), 5)
        clock.now = 172
        with self.assertRaises(BudgetDenied):
            budget.seconds("encrypt")
        clock.now = 176
        with self.assertRaises(BudgetDenied):
            budget.seconds("head")

    def test_late_success_is_rejected_without_relying_on_signal_state(self):
        clock = Clock(100)
        budget = self.budget(clock)
        self.assertEqual(budget.seconds("decrypt"), 76)
        clock.now = 180
        with self.assertRaises(BudgetDenied):
            budget.checkpoint()

    def test_rollback_or_nonfinite_clock_permanently_invalidates_session(self):
        for invalid in (99, float("nan"), float("inf"), True):
            clock = Clock(100)
            budget = self.budget(clock)
            clock.now = invalid
            with (
                self.subTest(type=type(invalid).__name__),
                self.assertRaises(BudgetDenied),
            ):
                budget.seconds("head")
            clock.now = 110
            with self.assertRaises(BudgetDenied):
                budget.seconds("head")

    def test_malformed_expired_future_and_unbounded_inputs_fail_closed(self):
        for value in (True, None, "180", -1, float("nan"), float("inf"), 10**1000):
            with (
                self.subTest(type=type(value).__name__),
                self.assertRaises(BudgetDenied),
            ):
                self.budget(Clock(100), owner_end=value)
        for changes in (
            {"install_started": 101},
            {"owner_end": 100},
            {"client_end": 99},
            {"run_end": 0},
        ):
            with self.subTest(field=list(changes)), self.assertRaises(BudgetDenied):
                self.budget(Clock(100), **changes)
        budget = self.budget(Clock())
        for operation, cap in (
            ("shell", None),
            ([], None),
            ("head", 21),
            ("encrypt", 121),
            ("decrypt", True),
            ("sql_restore", float("nan")),
        ):
            with (
                self.subTest(type=type(operation).__name__),
                self.assertRaises(BudgetDenied),
            ):
                budget.seconds(operation, cap)


if __name__ == "__main__":
    unittest.main()
