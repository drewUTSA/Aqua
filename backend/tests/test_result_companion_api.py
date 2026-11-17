"""Real private storage/session tests; the saved analysis engine is synthetic."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

import main
from companion.policy import CompanionPolicy
from result_companion_fixtures import response

PATH = "/api/v1/companion/result-brief"


def body(request, **changes):
    return {"schemaVersion": 1, "request_id": request, "column_index": 0, **changes}


@pytest.fixture
def enabled(world, monkeypatch):
    monkeypatch.setattr(main.app.state, "companion_policy", CompanionPolicy(True))

    def answer(question, model, session, settings):
        world.calls.append((question, model, session.user["id"]))
        return response(truncated=True)

    monkeypatch.setattr(main.app.state, "workspace_query", answer)
    return world


def test_brief_uses_owned_saved_truth_without_new_analysis_history_or_implied_currency(
    enabled,
):
    client, owner = enabled.client()
    saved = enabled.submit(client, "Original synthetic question")
    request = saved["request"]["id"]
    before = client.get(f"/api/v1/chats/{saved['chat']['id']}/messages").json()
    result = client.post(PATH, json=body(request))
    assert result.status_code == 200, result.text
    value = result.json()
    assert value["owner_id"] == owner and value["request_id"] == request
    assert (
        value["chat_id"] == saved["chat"]["id"]
        and value["assistant_message_id"] == saved["assistant_message"]["id"]
    )
    assert value["brief"]["numeric"]["minimum"]["value"] == "-3.5"
    assert value["brief"]["counts"]["missing_values"] == 1
    assert (
        value["brief"]["field"]["unit"] is None
        and value["brief"]["execution_enabled"] is False
    )
    assert len(result.content) <= 32768 and "PRIVATE_SQL_CANARY" not in result.text
    assert (
        result.headers["cache-control"] == "no-store"
        and "cookie" in result.headers["vary"].lower()
    )
    assert result.headers.get("x-aqua-history-revision")
    assert (
        len(enabled.calls) == 1
        and client.get(f"/api/v1/chats/{saved['chat']['id']}/messages").json() == before
    )


def test_default_off_and_foreign_missing_ids_are_denied(enabled, monkeypatch):
    first, _ = enabled.client("A")
    second, _ = enabled.client("B")
    saved = enabled.submit(first)
    request = saved["request"]["id"]
    for target in (request, str(uuid4())):
        result = second.post(PATH, json=body(target))
        assert result.status_code == 404 and "PRIVATE" not in result.text
    monkeypatch.setattr(main.app.state, "companion_policy", CompanionPolicy())
    assert first.post(PATH, json=body(request)).status_code == 404
    assert len(enabled.calls) == 1


@pytest.mark.parametrize(
    "change,status",
    [
        ("grant", 403),
        ("grant_version", 403),
        ("dataset", 403),
        ("history", 409),
        ("session", 401),
        ("delete", 404),
    ],
)
def test_current_session_grant_job_version_history_and_chat_are_reauthorized(
    enabled, change, status
):
    client, owner = enabled.client()
    saved = enabled.submit(client)
    request = saved["request"]["id"]
    if change == "delete":
        assert (
            client.delete(
                f"/api/v1/chats/{saved['chat']['id']}?revision={saved['chat']['revision']}"
            ).status_code
            == 204
        )
    else:
        with enabled.storage.transaction() as conn:
            if change == "grant":
                conn.execute(
                    "UPDATE app.dataset_grants SET revoked_at=clock_timestamp() WHERE user_id=%s",
                    (owner,),
                )
            elif change == "grant_version":
                conn.execute(
                    "UPDATE app.analysis_jobs SET grant_version=grant_version+1 WHERE user_id=%s AND id=%s",
                    (owner, request),
                )
            elif change == "dataset":
                conn.execute(
                    "UPDATE app.analysis_jobs SET dataset_key='other-synthetic-dataset' WHERE user_id=%s AND id=%s",
                    (owner, request),
                )
            elif change == "history":
                conn.execute(
                    "UPDATE app.analysis_jobs SET history_generation=history_generation+1 WHERE user_id=%s AND id=%s",
                    (owner, request),
                )
            else:
                conn.execute(
                    "UPDATE app.sessions SET revoked_at=clock_timestamp() WHERE user_id=%s",
                    (owner,),
                )
    result = client.post(PATH, json=body(request))
    assert result.status_code == status, result.text
    assert "PRIVATE" not in result.text and len(enabled.calls) == 1


def test_unfinished_request_is_not_executed_to_generate_a_brief(enabled):
    client, _ = enabled.client()
    queued = client.post("/api/v1/chats", json=enabled.body()).json()
    result = client.post(PATH, json=body(queued["request"]["id"]))
    assert result.status_code == 404 and enabled.calls == []


def test_old_saved_result_is_limited_without_being_rewritten_or_regenerated(
    enabled, monkeypatch
):
    def answer(*args):
        enabled.calls.append("synthetic-original")
        return response(metadata=False)

    monkeypatch.setattr(main.app.state, "workspace_query", answer)
    client, _ = enabled.client()
    saved = enabled.submit(client)
    result = client.post(PATH, json=body(saved["request"]["id"]))
    assert result.status_code == 200 and result.json()["brief"]["status"] == "limited"
    assert result.json()["brief"]["numeric"] is None and len(enabled.calls) == 1


def test_closed_input_media_and_csrf_are_checked_without_echo(enabled, monkeypatch):
    client, _ = enabled.client()
    saved = enabled.submit(client)
    request = saved["request"]["id"]
    for changes in (
        {"schemaVersion": True},
        {"column_index": True},
        {"column_index": 64},
        {"column_index": 1},
        {"request_id": "PRIVATE_CANARY"},
        {"owner_id": "PRIVATE_CANARY"},
        {"rows": []},
        {"sql": "PRIVATE_CANARY"},
        {"unit": "USD"},
    ):
        result = client.post(PATH, json=body(request, **changes))
        assert result.status_code == 422 and "PRIVATE_CANARY" not in result.text
    assert (
        client.post(PATH + "?owner=PRIVATE_CANARY", json=body(request)).status_code
        == 422
    )
    assert (
        client.post(
            PATH, content="PRIVATE_CANARY", headers={"Content-Type": "text/plain"}
        ).status_code
        == 415
    )
    assert (
        client.post(
            PATH, json=body(request), headers={"Origin": "https://foreign.invalid"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            PATH, json=body(request), headers={"X-CSRF-Token": "foreign"}
        ).status_code
        == 403
    )
    monkeypatch.setattr(
        main.app.state, "retirement", SimpleNamespace(ready=False), raising=False
    )
    assert client.post(PATH, json=body(request)).status_code == 503
    assert len(enabled.calls) == 1


@pytest.mark.parametrize(
    "attack",
    [
        "duplicate",
        "escaped_duplicate",
        "utf16",
        "bom",
        "invalid_utf8",
        "nul",
        "oversize",
    ],
)
def test_small_unambiguous_utf8_body_is_specific_to_this_new_route(enabled, attack):
    client, _ = enabled.client()
    raw = json.dumps(body(str(uuid4()))).encode()
    status = 422
    if attack == "duplicate":
        raw = raw[:-1] + b',"column_index":0}'
    elif attack == "escaped_duplicate":
        raw = raw[:-1] + b',"column\\u005findex":0}'
    elif attack == "utf16":
        raw = raw.decode().encode("utf-16")
    elif attack == "bom":
        raw = b"\xef\xbb\xbf" + raw
    elif attack == "invalid_utf8":
        raw += b"\xff"
    elif attack == "nul":
        raw += b"\x00"
    else:
        raw = b" " * (8193 - len(raw)) + raw
        status = 413
    result = client.post(
        PATH, content=raw, headers={"Content-Type": "application/json"}
    )
    assert (
        result.status_code == status
        and len(result.content) < 512
        and enabled.calls == []
    )
    # Existing help retains its16KiB body allowance and normal lookup behavior.
    old = json.dumps({"schemaVersion": 1, "question": "charts"}).encode()
    old = b" " * (9000 - len(old)) + old
    assert (
        client.post(
            "/api/v1/companion/help",
            content=old,
            headers={"Content-Type": "application/json"},
        ).status_code
        == 200
    )


def test_reads_share_the_existing_committed_workspace_allowance(enabled):
    client, owner = enabled.client()
    saved = enabled.submit(client)
    for _ in range(59):
        assert client.post(PATH, json=body(saved["request"]["id"])).status_code == 200
    assert client.post(PATH, json=body(saved["request"]["id"])).status_code == 429
    with enabled.storage.transaction() as conn:
        assert conn.execute(
            "SELECT hits FROM app.workspace_admission WHERE user_id=%s", (owner,)
        ).fetchone() == (60,)
    assert len(enabled.calls) == 1
