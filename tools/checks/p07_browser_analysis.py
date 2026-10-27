"""Closed fake engine for actual DB lifecycle journeys; never a provider client."""

import threading
import time
from types import SimpleNamespace
from typing import Any

from p06_browser_analysis import AnalysisFixture, DATASET

HELD = frozenset(
    {
        "P07 fixture held generation",
        "P07 fixture held execution",
        "P07 fixture reconnect",
    }
)


class LifecycleFixture(AnalysisFixture):
    def __init__(self, storage: Any, settings: Any) -> None:
        super().__init__(storage, settings)
        self.max_executions = 24
        self.lock = threading.Lock()
        self.release = threading.Event()
        self.closed = threading.Event()
        self.active = self.maximum_active = self.cancelled = 0
        self.started = 0
        self.execution_cancelled = self.context_turns = 0
        self.held: str | None = None
        self.restarted = False
        self.restart: Any = None

    def control(self, item: dict[str, Any]) -> dict[str, Any]:
        if set(item) != {"id", "kind"}:
            raise ValueError("fixture_analysis_control_invalid")
        kind = item["kind"]
        if kind == "workspace_release":
            with self.lock:
                if self.held not in HELD or self.release.is_set():
                    raise ValueError("fixture_release_unavailable")
                self.release.set()
            return {"id": item["id"], "kind": kind, "released": True}
        if kind == "workspace_restart":
            if self.restarted or self.restart is None:
                raise ValueError("fixture_restart_unavailable")
            self.restarted = True
            self.restart()
            return {"id": item["id"], "kind": kind, "restarted": True}
        if kind == "workspace_recover_analysis_rate":
            if self.owner is None or self.retired:
                raise ValueError("fixture_analysis_rate_recovery_unavailable")
            # Explicit fixture clock step; actual runtime admission remains on.
            with self.storage.transaction() as conn:
                conn.execute(
                    "UPDATE app.analysis_admission SET expires_at=clock_timestamp()-interval '1 second'"
                )
            return {
                "id": item["id"],
                "kind": kind,
                "scope": "synthetic_analysis_admission_only",
            }
        if kind == "workspace_stats":
            with self.lock:
                return {
                    "id": item["id"],
                    "kind": kind,
                    "fake_executions": self.executions,
                    "fake_started": self.started,
                    "actual_provider_calls": 0,
                    "physical_active": self.active,
                    "maximum_physical_active": self.maximum_active,
                    "cancelled_executions": self.cancelled,
                    "fake_query_cancellations": self.execution_cancelled,
                    "last_context_turns": self.context_turns,
                }
        return super().control(item)

    def run(self, payload: dict, control: Any) -> tuple[dict, int]:
        from analysis.dispatch import Halt

        question = payload["question"]
        if payload["settings"]["database_url"] != DATASET:
            raise AssertionError("fixture_analysis_connection_denied")
        context = payload["context"]
        if len(context) > 8 or any(
            set(turn) - {"message_id", "sequence", "question", "sql"}
            for turn in context
        ):
            raise AssertionError("fixture_context_shape_invalid")
        stage = (
            "executing" if question == "P07 fixture held execution" else "generating"
        )
        with self.lock:
            if (
                self.closed.is_set()
                or self.active
                or self.started >= self.max_executions
            ):
                raise AssertionError("fixture_physical_budget_exceeded")
            self.active += 1
            self.started += 1
            self.maximum_active = max(self.active, self.maximum_active)
            self.context_turns = len(context)
            if question in HELD:
                self.held = question
                self.release.clear()
        try:
            control(stage)
            if question in HELD:
                deadline = time.monotonic() + 30
                while not self.release.wait(0.05):
                    control(None)
                    if self.closed.is_set() or time.monotonic() >= deadline:
                        raise Halt("interrupted")
            session = SimpleNamespace(user={"id": payload["principal"]}, can_query=True)
            answer = self.answer(question, payload["model"], session, self.settings)
            if question == "P07 fixture exact precision":
                from decimal import Decimal
                from nl2sql.pipeline import Answer
                from nl2sql.response import to_response
                from nl2sql.result_metadata import metadata_for

                result = Answer(
                    question,
                    "SELECT approved_fixture_values",
                    columns=["exact_integer", "exact_decimal"],
                    rows=[
                        (Decimal("9007199254740993"), Decimal("-0.1234567890123456789"))
                    ],
                    model="fixture-only",
                )
                metadata = metadata_for(result, source_id=self.dataset)
                answer = to_response(result)
                answer["result_metadata"] = metadata
            if question == "P07 fixture follow-up":
                if not context:
                    raise AssertionError("fixture_follow_up_context_missing")
                answer["message"] = (
                    "Synthetic follow-up used its earlier saved question."
                )
            control("summarizing")
            return answer, 200
        except Halt as error:
            if error.state == "cancelled":
                with self.lock:
                    self.cancelled += 1
                    self.execution_cancelled += int(stage == "executing")
            raise
        finally:
            with self.lock:
                self.active -= 1
                self.held = None

    def close(self) -> None:
        self.closed.set()

    def reopen(self) -> None:
        with self.lock:
            if self.active:
                raise AssertionError("fixture_restart_child_not_reaped")
            self.closed.clear()
