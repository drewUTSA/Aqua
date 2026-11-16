"""Production prompt/provider capture is offline and never receives gold SQL."""

import json
import time
import pytest

from eval.local_model_capture import Client, body_digest
from nl2sql.config import Settings
from nl2sql.control import Budget, CURRENT
from nl2sql.generate import generate_sql


def test_production_request_capture_and_response_replay_are_identical():
    settings = Settings(
        ollama_model="qwen3:4b",
        ollama_think=False,
        llm_provider="ollama",
        llm_fallback=False,
    )
    token = CURRENT.set(Budget(time.monotonic() + 120, lambda stage: None))
    try:
        capture = Client()
        generate_sql(
            "Count account rows",
            "CREATE TABLE account(account_id int);",
            settings,
            client=capture,
        )
        raw = json.dumps(
            {
                "model": "qwen3:4b",
                "done": True,
                "message": {"content": '{"sql":"SELECT COUNT(*) FROM account"}'},
            }
        ).encode()
        replay = Client(raw, body_digest(capture.body))
        result = generate_sql(
            "Count account rows",
            "CREATE TABLE account(account_id int);",
            settings,
            client=replay,
        )
        assert result.sql == "SELECT COUNT(*) FROM account"
        assert capture.body == replay.body
        assert capture.body["think"] is False and capture.calls == replay.calls == 1
        assert "SELECT COUNT(*) FROM account" not in json.dumps(capture.body)
        assert CURRENT.get().calls == 2
    finally:
        CURRENT.reset(token)


def test_changed_production_request_cannot_receive_a_captured_response():
    client = Client(expected="a" * 64)
    with pytest.raises(ValueError, match="production_request_changed"):
        client.stream(
            "POST", "http://127.0.0.1:11434/api/chat", json={"synthetic": True}
        )
