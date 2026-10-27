"""Transport replay, concurrent ordering, revocation and deletion completion fences."""

from concurrent.futures import ThreadPoolExecutor
import threading
from uuid import uuid4

import pytest

from workspace_fixtures import GOOD


def test_duplicate_inflight_submission_returns_same_ids_without_duplicate_work(
    world, monkeypatch
):
    a, _ = world.client()
    entered, release = threading.Event(), threading.Event()

    def blocking(*args):
        result = world.answer(*args)
        entered.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(__import__("main").app.state, "workspace_query", blocking)
    body = world.body("Once only")
    first = a.post("/api/v1/chats", json=body)
    assert first.status_code == 202
    with ThreadPoolExecutor(max_workers=1) as worker:
        work = worker.submit(world.analysis.tick)
        assert entered.wait(3)
        try:
            duplicate = a.post("/api/v1/chats", json=body)
            assert duplicate.status_code == 202, duplicate.text
            assert duplicate.json()["request"]["state"] == "running"
            assert (
                a.post(
                    "/api/v1/chats", json={**body, "question": "Changed"}
                ).status_code
                == 409
            )
        finally:
            release.set()
        assert work.result(timeout=3)
    completed = a.get("/api/v1/analysis-requests/" + first.json()["request"]["id"])
    assert completed.status_code == 200
    assert completed.json()["request"]["id"] == duplicate.json()["request"]["id"]
    assert len(world.calls) == 1


@pytest.mark.parametrize("race", ["delete", "revoke", "logout"])
def test_late_completion_does_not_restore_deleted_or_revoked_content(
    world, monkeypatch, race
):
    a, owner = world.client()

    def racing(*args):
        with world.storage.transaction() as conn:
            chat_id, revision = conn.execute(
                "SELECT id,revision FROM app.chats WHERE user_id=%s", (owner,)
            ).fetchone()
        if race == "delete":
            assert (
                a.delete(f"/api/v1/chats/{chat_id}?revision={revision}").status_code
                == 204
            )
        else:
            with world.storage.transaction() as conn:
                if race == "revoke":
                    conn.execute(
                        "UPDATE app.dataset_grants SET revoked_at=clock_timestamp() WHERE user_id=%s",
                        (owner,),
                    )
                else:
                    conn.execute(
                        "UPDATE app.sessions SET revoked_at=clock_timestamp() WHERE user_id=%s",
                        (owner,),
                    )
        return GOOD.copy()

    monkeypatch.setattr(__import__("main").app.state, "workspace_query", racing)
    response = a.post("/api/v1/chats", json=world.body())
    assert response.status_code == 202
    assert world.analysis.tick()
    response = a.get("/api/v1/analysis-requests/" + response.json()["request"]["id"])
    assert (
        response.status_code == {"delete": 404, "revoke": 403, "logout": 401}[race]
    ), response.text
    with world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.visual_results WHERE user_id=%s", (owner,)
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT state,reserved_bytes FROM app.analysis_requests WHERE user_id=%s",
            (owner,),
        ).fetchone() == ("interrupted", 0)


def test_explicit_retry_uses_original_input_but_creates_only_one_new_assistant_attempt(
    world, monkeypatch
):
    a, _ = world.client()
    failure = {
        **GOOD,
        "status": "error",
        "error": {
            "code": "model_unavailable",
            "message": "Try later",
            "retryable": True,
        },
        "tables": [],
        "sql": "",
    }
    monkeypatch.setattr(
        __import__("main").app.state, "workspace_query", lambda *args: failure.copy()
    )
    saved = world.submit(a)
    monkeypatch.setattr(__import__("main").app.state, "workspace_query", world.answer)
    path = f"/api/v1/chats/{saved['chat']['id']}/messages/{saved['input_message']['id']}/retries"
    body = {"client_request_id": str(uuid4())}
    retry = a.post(path, json=body)
    assert retry.status_code == 202, retry.text
    assert retry.json()["input_message"]["id"] == saved["input_message"]["id"]
    assert retry.json()["assistant_message"]["id"] != saved["assistant_message"]["id"]
    assert retry.json()["chat"]["message_count"] == 3
    assert a.post(path, json=body).json() == retry.json()
    assert world.analysis.tick()
    assert len(world.calls) == 1


def test_order_is_reserved_while_earlier_execution_is_still_running(world, monkeypatch):
    a, _ = world.client()
    saved = world.submit(a)
    entered, release = threading.Event(), threading.Event()

    def run(question, *args):
        if question == "Earlier":
            entered.set()
            assert release.wait(5)
        return GOOD.copy()

    monkeypatch.setattr(__import__("main").app.state, "workspace_query", run)
    path = f"/api/v1/chats/{saved['chat']['id']}/messages"
    earlier = a.post(path, json=world.body("Earlier"))
    assert earlier.status_code == 202
    with ThreadPoolExecutor(max_workers=1) as worker:
        running = worker.submit(world.analysis.tick)
        assert entered.wait(3)
        try:
            later = a.post(path, json=world.body("Later"))
            assert later.status_code == 202
            assert not world.analysis.tick()  # One real execution slot per owner.
        finally:
            release.set()
        assert running.result(timeout=3)
    assert world.analysis.tick()
    page = a.get(path).json()["items"]
    assert [item["sequence"] for item in page] == [1, 2, 3, 4, 5, 6]
    assert page[2]["content"] == "Earlier" and page[4]["content"] == "Later"
