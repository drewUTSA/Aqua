"""Closed P08 result cases over real private auth/history, without source SQL."""

import datetime as dt
from decimal import Decimal
import threading
from typing import Any

from p07_browser_analysis import LifecycleFixture

CASES = frozenset(
    {
        "P08 chart primitives",
        "P08 chart hostile labels",
        "P08 chart UTC time",
        "P08 chart exact values",
        "P08 chart oversized",
        "P08 chart failure",
        "P08 text explanation",
        "Can you explain the chart?",
        "Now by category",
    }
)


class VisualFixture(LifecycleFixture):
    """At most twelve fixed fake jobs; normal grants/leases remain enforced."""

    def __init__(self, storage: Any, settings: Any) -> None:
        super().__init__(storage, settings)
        self.max_executions = 12
        self.local = threading.local()

    def control(self, item: dict[str, Any]) -> dict[str, Any]:
        result = super().control(item)
        if item.get("kind") == "workspace_stats":
            result["p08_presentation_fixture"] = True
        return result

    def run(self, payload: dict, control: Any) -> tuple[dict, int]:
        if payload.get("question") not in CASES:
            raise AssertionError("fixture_visual_case_denied")
        self.local.context = payload["context"]
        try:
            return super().run(payload, control)
        finally:
            self.local.context = ()

    def answer(
        self, question: str, model: str, session: Any, settings: Any
    ) -> dict[str, Any]:
        # The inherited guard proves the sole granted synthetic owner, fake
        # dataset and bounded execution count before constructing any result.
        super().answer(question, model, session, settings)
        from nl2sql.pipeline import Answer
        from nl2sql.presentation import presentation_for
        from nl2sql.response import outage_response, to_response
        from nl2sql.result_metadata import metadata_for

        if question == "P08 chart failure":
            return outage_response(
                "model_unavailable", "Synthetic visual refresh failed."
            )
        columns = ["category", "measure"]
        rows: list[tuple[Any, ...]] = [
            ("Zero", 0),
            ("Negative", -12.5),
            ("Missing", None),
        ]
        if question == "P08 chart hostile labels":
            rows = [
                ('<img src="https://outside.invalid/track" onerror="PRIVATE()">', 2),
                (' \t=HYPERLINK("https://outside.invalid")', -1),
                ("Ampersand & <literal>", 0),
            ]
        elif question == "P08 chart UTC time":
            columns = ["instant", "amount"]
            rows = [
                (dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc), 0),
                (
                    dt.datetime(
                        2025, 12, 31, 20, tzinfo=dt.timezone(dt.timedelta(hours=-5))
                    ),
                    -2,
                ),
                (dt.datetime(2026, 1, 1, 2, tzinfo=dt.timezone.utc), None),
            ]
        elif question == "P08 chart exact values":
            rows = [
                ("Exact integer", Decimal("9007199254740993")),
                ("Exact decimal", Decimal("-0.1234567890123456789")),
            ]
        elif question == "P08 chart oversized":
            rows = [(f"Category {index}", index) for index in range(51)]
        elif question == "Now by category":
            rows = [("Zero", 0), ("Negative", -25), ("Missing", None)]
        result = Answer(
            question,
            (
                "SELECT fixed_synthetic_filtered_values"
                if question == "Now by category"
                else "SELECT fixed_synthetic_fixture_values"
            ),
            columns=columns,
            rows=rows,
            model="fixture-only",
        )
        metadata = metadata_for(result, source_id=self.dataset)
        response = to_response(result)
        response["result_metadata"] = metadata
        response["presentation"] = presentation_for(
            result, response, metadata, context=getattr(self.local, "context", ())
        )
        return response


class ResultBriefFixture(VisualFixture):
    """Two ordinary visual cases in the opt-in saved-result browser journey."""

    result_brief_enabled = True

    def __init__(self, storage: Any, settings: Any) -> None:
        super().__init__(storage, settings)
        from companion.policy import CompanionPolicy
        from main import app

        app.state.companion_policy = CompanionPolicy(enabled=True)
        self.max_executions = 2
        self.provider_attempts = 0

    def run(self, payload: dict, control: Any) -> tuple[dict, int]:
        if payload.get("question") not in {
            "P08 chart primitives",
            "P08 chart exact values",
        }:
            raise AssertionError("fixture_result_case_denied")
        return super().run(payload, control)

    def control(self, item: dict[str, Any]) -> dict[str, Any]:
        result = super().control(item)
        if item["kind"] == "workspace_stats":
            with self.storage.transaction() as conn:
                jobs, messages = conn.execute(
                    "SELECT (SELECT count(*) FROM app.analysis_jobs WHERE user_id=%s),"
                    "(SELECT count(*) FROM app.messages WHERE user_id=%s)",
                    (self.owner, self.owner),
                ).fetchone()
            result.update(
                result_brief_jobs=jobs,
                result_brief_messages=messages,
                actual_provider_calls=self.provider_attempts,
            )
        return result
