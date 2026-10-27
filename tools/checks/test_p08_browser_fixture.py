"""Offline boundary checks for the opt-in P08 browser-only injection seam."""

import inspect
import threading
import unittest
from unittest.mock import patch

from p07_browser_analysis import LifecycleFixture
from p08_browser_fixture import CASES, VisualFixture
from p08_browser_host import MAX_OPERATIONS, MAX_SECONDS


class VisualBoundaryTests(unittest.TestCase):
    def fixture(self) -> VisualFixture:
        # Avoid importing runtime auth/dependencies: the run-boundary check is
        # deliberately before the inherited engine sees any storage/provider.
        fixture = VisualFixture.__new__(VisualFixture)
        fixture.local = threading.local()
        return fixture

    def test_unknown_questions_cannot_reach_inherited_engine(self) -> None:
        fixture = self.fixture()
        with patch.object(LifecycleFixture, "run") as inherited:
            for question in ("SELECT private", "P08 chart arbitrary URL", "", None):
                with self.assertRaisesRegex(
                    AssertionError, "fixture_visual_case_denied"
                ):
                    fixture.run({"question": question}, lambda _stage: None)
            inherited.assert_not_called()

    def test_only_fixed_cases_pass_frozen_context_then_clear_it(self) -> None:
        fixture = self.fixture()
        context = [{"question": "fixed synthetic prior turn"}]
        for question in CASES:

            def inherited(_self, payload, _control):
                self.assertIs(fixture.local.context, context)
                self.assertEqual(payload["question"], question)
                return {"status": "success"}, 200

            with patch.object(LifecycleFixture, "run", inherited):
                self.assertEqual(
                    fixture.run({"question": question, "context": context}, None)[1],
                    200,
                )
            self.assertEqual(fixture.local.context, ())

    def test_engine_failure_also_clears_private_context(self) -> None:
        fixture = self.fixture()
        with patch.object(LifecycleFixture, "run", side_effect=RuntimeError("fixed")):
            with self.assertRaises(RuntimeError):
                fixture.run({"question": next(iter(CASES)), "context": ["fixed"]}, None)
        self.assertEqual(fixture.local.context, ())

    def test_worker_hook_is_keyword_only_and_defaults_closed(self) -> None:
        from p05_browser_worker import worker

        parameter = inspect.signature(worker).parameters["analysis_factory"]
        self.assertIs(parameter.default, None)
        self.assertEqual(parameter.kind, inspect.Parameter.KEYWORD_ONLY)

    def test_host_and_fake_job_limits_are_finite(self) -> None:
        self.assertEqual(len(CASES), 9)
        self.assertEqual(MAX_OPERATIONS, 200)
        self.assertEqual(MAX_SECONDS, 180)
        source = inspect.getsource(VisualFixture.__init__)
        self.assertIn("self.max_executions = 12", source)


if __name__ == "__main__":
    unittest.main()
