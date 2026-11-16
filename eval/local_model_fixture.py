"""Closed synthetic prepare/score subprocess; never receives a provider or live DSN."""

import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend"), str(ROOT / "backend/tests")]


def main():
    if (
        len(sys.argv) != 3
        or sys.argv[1] not in {"bank", "pagila"}
        or sys.argv[2] not in {"prepare", "score"}
    ):
        raise ValueError("closed_fixture_action_required")
    dataset, action = sys.argv[1:]
    os.environ["AQUA_TEST_DATASET"] = dataset
    from safety import install

    install()
    from eval.replay_data import load
    from eval.local_model_capture import Client, body_digest
    from nl2sql.config import Settings
    from nl2sql.db import connect
    from nl2sql.execute import execute, QueryError
    from nl2sql.schema import load_schema
    from nl2sql.validate import validate_sql, UnsafeQueryError
    from nl2sql.generate import generate_sql
    from nl2sql.control import Budget, CURRENT
    from nl2sql.llm import LLMError

    raw = sys.stdin.buffer.read(2200001)
    if len(raw) > 2200000:
        raise ValueError("fixture_input_budget")
    value = json.loads(raw)
    if type(value) is not dict or set(value) != (
        {"id"} if action == "prepare" else {"id", "response", "request_sha256"}
    ):
        raise ValueError("fixture_fields_invalid")
    cases, _ = load(
        (ROOT / "tools/checks/fixtures/ai_replay_dataset.jsonl").read_bytes()
    )
    selected = [
        c
        for c in cases
        if c["id"] == value["id"] and c["dataset"] == dataset and c["kind"] == "answer"
    ]
    if len(selected) != 1:
        raise ValueError("fixture_case_invalid")
    case = selected[0]
    settings = Settings(
        database_url=f"postgresql://nl2sql_reader@127.0.0.1:5432/aqua_test_{dataset}",
        ollama_model="qwen3:4b",
        ollama_think=False,
        llm_provider="ollama",
        llm_fallback=False,
    )
    CURRENT.set(Budget(time.monotonic() + 120, lambda stage: None))
    with connect(settings) as conn:
        schema = load_schema(conn)
    # Independent fixture facts validate the gold before any generation is requested.
    gold = execute(
        validate_sql(case["sql"], allowed_tables=schema.allowed_tables),
        settings,
        max_rows=10,
    )
    if gold.truncated or gold.rows != [tuple(row) for row in case["expected"]]:
        raise ValueError("fixture_gold_mismatch")
    if action == "prepare":
        prompt = schema.to_prompt()
        if len(prompt.encode()) > 60000:
            raise ValueError("fixture_schema_budget")
        client = Client()
        generate_sql(case["question"], prompt, settings, client=client)
        result = {"body": client.body, "request_sha256": body_digest(client.body)}
    else:
        response = value["response"]
        if type(response) is not str or len(response.encode()) > 1048576:
            raise ValueError("fixture_response_budget")
        parsed = json.loads(response)
        if (
            type(parsed) is not dict
            or parsed.get("model") != "qwen3:4b"
            or parsed.get("done") is not True
        ):
            raise ValueError("fixture_model_completion_invalid")
        try:
            client = Client(response.encode(), value["request_sha256"])
            generation = generate_sql(
                case["question"], schema.to_prompt(), settings, client=client
            )
            prediction = execute(
                validate_sql(generation.sql, allowed_tables=schema.allowed_tables),
                settings,
                max_rows=10,
            )
            result = {
                "status": (
                    "correct"
                    if not prediction.truncated and prediction.rows == gold.rows
                    else "incorrect"
                )
            }
        except UnsafeQueryError:
            result = {"status": "sql_denied"}
        except QueryError:
            result = {"status": "query_failed"}
        except LLMError:
            result = {"status": "provider_reply_invalid"}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
