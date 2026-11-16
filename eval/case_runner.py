"""Bound each evaluation case while keeping runtime operations injectable."""

from typing import Any

from nl2sql.control import Budget, CURRENT, ExecutionStopped, stage
from nl2sql.db import DatabaseError
from nl2sql.errors import ContextDenied
from nl2sql.execute import QueryError
from nl2sql.llm import LLMError
from nl2sql.validate import UnsafeQueryError


def check_gold(
    items: list[dict[str, Any]], settings, schema, *, gold_runner, clock
) -> int:
    """Run every gold query; report any that fail or return nothing."""
    problems = 0
    for item in items:
        token = CURRENT.set(Budget(clock.monotonic() + 120, lambda name: None))
        try:
            stage("gold")
            rows = gold_runner(item, settings, schema)
            CURRENT.get().remaining()
        except Exception:  # noqa: BLE001 - complete, fixed diagnostic only
            print("FAIL gold_query_failed")
            problems += 1
            continue
        finally:
            CURRENT.reset(token)
        flag = "" if rows else "  <- returns no rows"
        print(f"ok: {len(rows)} row(s){flag}")
    print(f"\n{len(items) - problems} of {len(items)} gold queries ran.")
    return 1 if problems else 0


def evaluate(
    item: dict[str, Any],
    settings,
    schema,
    retriever,
    *,
    gold_runner,
    pipeline,
    exact_scorer,
    lenient_scorer,
    clock,
) -> dict[str, Any]:
    record = {
        "id": item["id"],
        "difficulty": item["difficulty"],
        "question": item["question"],
        "gold_sql": item["sql"],
        "exact": False,
        "lenient": False,
    }
    started = clock.perf_counter()
    last_stage = ["gold", started]
    timings: dict[str, float] = {}

    def notify(name: str) -> None:
        now = clock.perf_counter()
        previous, since = last_stage
        timings[previous] = timings.get(previous, 0.0) + max(0.0, now - since)
        last_stage[:] = [
            (
                name
                if name
                in {
                    "gold",
                    "retrieval",
                    "generating",
                    "validating",
                    "executing",
                    "scoring",
                }
                else "other"
            ),
            now,
        ]

    budget = Budget(clock.monotonic() + 120, notify)
    token = CURRENT.set(budget)
    try:
        stage("gold")
        gold = gold_runner(item, settings, schema)
        budget.remaining()
        answer = pipeline(item["question"], settings, schema, retriever=retriever)
        stage("scoring")
        record |= {
            "sql": answer.sql,
            "attempts": answer.attempts,
            "used_retrieval": answer.used_retrieval,
            "answered_by": answer.model,
        }
        if answer.error is not None:
            record["status"] = (
                answer.error_code
                if answer.error_code in {"rejected", "query_failed"}
                else "answer_failed"
            )
            record["error"] = "answer_unsuccessful"
        else:
            ordered = bool(item.get("ordered"))
            record |= {
                "status": "ok",
                "exact": exact_scorer(gold, answer.rows, ordered),
                "lenient": lenient_scorer(gold, answer.rows, ordered),
            }
        budget.remaining()
    except (LLMError, DatabaseError):
        record |= {"status": "outage", "error": "service_unavailable"}
    except (ContextDenied, UnsafeQueryError):
        record |= {"status": "denied", "error": "context_or_query_denied"}
    except ExecutionStopped:
        record |= {"status": "budget_exhausted", "error": "case_budget_exhausted"}
    except QueryError:
        record |= {"status": "gold_failed", "error": "gold_query_failed"}
    except Exception:  # noqa: BLE001 - preserve denominator, never exception text
        record |= {"status": "evaluation_failed", "error": "evaluation_failed"}
    finally:
        finished = clock.perf_counter()
        elapsed = finished - started
        previous, since = last_stage
        timings[previous] = timings.get(previous, 0.0) + max(0.0, finished - since)
        CURRENT.reset(token)
    if record["status"] != "ok":
        record.update(exact=False, lenient=False)
    return record | {
        # Never clip or round measurements to satisfy a gate. Over-budget
        # measurements remain visible and cause the offline gate to fail closed.
        "seconds": None if record["status"] == "outage" else elapsed,
        "elapsed_seconds": elapsed,
        "provider_calls": budget.calls,
        "stage_seconds": timings,
    }
