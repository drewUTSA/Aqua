"""The dataset approved by authentication is the one passed to query work."""

from dataclasses import replace

import pytest

import main
from nl2sql.cache import AnswerCache
from nl2sql.pipeline import Answer
from nl2sql.schema import Schema
from _durable_route_helpers import headers, login


@pytest.mark.parametrize("retrieval", [False, True], ids=["plain", "retrieval"])
def test_query_uses_current_approved_dataset_instead_of_module_global(
    durable_browser, monkeypatch, retrieval
):
    client, _, _, _ = durable_browser
    original = main.SETTINGS.database_url
    approved = "postgresql://nl2sql_reader@127.0.0.1:5432/aqua_test_approved"
    assert original != approved
    monkeypatch.setattr(
        main.app.state,
        "settings",
        replace(
            main.app.state.settings,
            database_url=approved,
            llm_provider="ollama",
            retrieval=retrieval,
        ),
    )
    payload, _ = login(durable_browser)
    assert payload["can_query"] is True
    queried = []

    def schema(settings):
        queried.append(settings.database_url)
        assert settings.database_url == approved
        return Schema(tables={})

    def answer(question, settings, current_schema, retriever=None):
        assert settings.database_url == approved
        if retrieval:
            assert retriever is not None and retriever.settings.database_url == approved
        else:
            assert retriever is None
        return Answer(question=question, sql="SELECT 1", columns=["n"], rows=[(1,)])

    monkeypatch.setattr(main, "get_schema", schema)
    monkeypatch.setattr(main, "answer_question", answer)
    response = client.post(
        "/api/query",
        json={"question": "Synthetic dataset binding", "model": "ollama"},
        headers=headers(payload["csrf_token"]),
    )
    assert response.status_code == 200 and queried == [approved]


def test_effective_provider_model_change_cannot_reuse_earlier_cached_answer(
    durable_browser, monkeypatch
):
    client, _, _, _ = durable_browser
    configured = replace(
        main.app.state.settings,
        llm_provider="gemini",
        gemini_api_key="fictional-key-no-provider-call",
        gemini_model="gemini-fixture-alpha",
        retrieval=False,
    )
    monkeypatch.setattr(main.app.state, "settings", configured)
    monkeypatch.setattr(main, "ANSWER_CACHE", AnswerCache(60))
    monkeypatch.setattr(main, "get_schema", lambda settings: Schema(tables={}))
    invoked = []

    def answer(question, settings, schema, retriever=None):
        invoked.append(settings.gemini_model)
        return Answer(
            question=question,
            sql="SELECT 1",
            columns=["n"],
            rows=[(1,)],
            model=settings.gemini_model,
        )

    monkeypatch.setattr(main, "answer_question", answer)
    payload, _ = login(durable_browser)
    first = client.post(
        "/api/query",
        json={"question": "Same synthetic cached question", "model": "gemini"},
        headers=headers(payload["csrf_token"]),
    )
    monkeypatch.setattr(
        main.app.state,
        "settings",
        replace(configured, gemini_model="gemini-fixture-beta"),
    )
    second = client.post(
        "/api/query",
        json={"question": "Same synthetic cached question", "model": "gemini"},
        headers=headers(payload["csrf_token"]),
    )
    assert first.status_code == second.status_code == 200
    assert invoked == ["gemini-fixture-alpha", "gemini-fixture-beta"]
    assert first.json()["model"] != second.json()["model"]
