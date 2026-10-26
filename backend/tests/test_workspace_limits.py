"""Bounded durable admission/storage denies work and permits normal recovery."""

from uuid import uuid4
import psycopg
from storage_fixtures import RUNTIME
from auth.password_limits import LOCK as PASSWORD_ADMISSION_LOCK


from workspace_fixtures import GOOD


def test_failed_foreign_writes_spend_shared_budget_then_cooldown_recovers(world):
    a, owner = world.client()
    foreign = str(uuid4())
    for _ in range(60):
        assert (
            a.patch(
                f"/api/v1/chats/{foreign}", json={"revision": 1, "title": "No"}
            ).status_code
            == 404
        )
    denied = a.post("/api/v1/chats", json=world.body())
    assert denied.status_code == 429 and denied.headers["Retry-After"] == "60"
    assert world.calls == []
    with world.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.workspace_admission SET expires_at=now()-interval '1 second' WHERE user_id=%s",
            (owner,),
        )
    assert a.post("/api/v1/chats", json=world.body()).status_code == 201
    assert len(world.calls) == 1


def test_account_byte_cap_denies_before_model_and_releases_after_delete(world):
    a, owner = world.client()
    saved = world.submit(a)
    with world.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.workspace_usage SET content_bytes=16777216 WHERE user_id=%s",
            (owner,),
        )
        conn.execute(
            "UPDATE app.workspace_totals SET content_bytes=(SELECT sum(content_bytes) FROM app.workspace_usage) WHERE singleton"
        )
    assert a.post("/api/v1/chats", json=world.body()).status_code == 429
    assert len(world.calls) == 1
    # Restore truthful accounting to the synthetic owned content before deletion.
    with world.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.workspace_usage SET content_bytes=(SELECT sum(octet_length(content)) FROM app.messages WHERE user_id=%s)+(SELECT sum(octet_length(response::text)) FROM app.visual_results WHERE user_id=%s)+(SELECT sum(octet_length(title)) FROM app.chats WHERE user_id=%s) WHERE user_id=%s",
            (owner, owner, owner, owner),
        )
        conn.execute(
            "UPDATE app.workspace_totals SET content_bytes=(SELECT sum(content_bytes) FROM app.workspace_usage) WHERE singleton"
        )
    assert (
        a.delete(
            f"/api/v1/chats/{saved['chat']['id']}?revision={saved['chat']['revision']}"
        ).status_code
        == 204
    )
    assert a.post("/api/v1/chats", json=world.body()).status_code == 201


def test_oversized_result_has_safe_saved_error_and_no_unbounded_payload(
    world, monkeypatch
):
    a, owner = world.client()
    monkeypatch.setattr(
        __import__("main").app.state,
        "workspace_query",
        lambda *args: {**GOOD, "message": "x" * 262145},
    )
    response = a.post("/api/v1/chats", json=world.body())
    assert response.status_code == 201
    assert response.json()["response"]["error"]["code"] == "result_too_large"
    with world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT max(octet_length(response::text))<1024 FROM app.visual_results WHERE user_id=%s",
            (owner,),
        ).fetchone() == (True,)


def test_chat_message_cap_is_checked_before_model(world):
    a, owner = world.client()
    saved = world.submit(a)
    with world.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.chats SET message_count=200,next_message_sequence=201 WHERE user_id=%s",
            (owner,),
        )
    assert (
        a.post(
            f"/api/v1/chats/{saved['chat']['id']}/messages", json=world.body()
        ).status_code
        == 429
    )
    assert len(world.calls) == 1


def test_global_logical_byte_cap_is_shared_across_accounts_and_recovers(world):
    a, _ = world.client()
    others = []
    with world.storage.transaction() as conn:
        for index in range(13):
            owner = conn.execute(
                "INSERT INTO app.users(status) VALUES('active') RETURNING id"
            ).fetchone()[0]
            others.append(owner)
            conn.execute(
                "INSERT INTO app.workspace_usage(user_id,content_bytes) VALUES(%s,%s)",
                (owner, 16777216 if index < 12 else 8388608),
            )
        conn.execute(
            "UPDATE app.workspace_totals SET content_bytes=(SELECT sum(content_bytes) FROM app.workspace_usage) WHERE singleton"
        )
    assert a.post("/api/v1/chats", json=world.body()).status_code == 429
    assert world.calls == []
    with world.storage.transaction() as conn:
        conn.execute("DELETE FROM app.workspace_usage WHERE user_id=%s", (others[-1],))
        conn.execute(
            "UPDATE app.workspace_totals SET content_bytes=(SELECT sum(content_bytes) FROM app.workspace_usage) WHERE singleton"
        )
    assert a.post("/api/v1/chats", json=world.body()).status_code == 201


def test_project_and_prompt_count_caps_fail_without_creating_extra_rows(world):
    a, owner = world.client(grant=False)
    with world.storage.transaction() as conn:
        conn.execute(
            "INSERT INTO app.projects(user_id,name,client_request_id,fingerprint) SELECT %s,'Project',gen_random_uuid(),decode(repeat('ab',32),'hex') FROM generate_series(1,20)",
            (owner,),
        )
        conn.execute(
            "INSERT INTO app.saved_prompts(user_id,label,prompt,client_request_id,fingerprint) SELECT %s,'Label','Prompt',gen_random_uuid(),decode(repeat('cd',32),'hex') FROM generate_series(1,100)",
            (owner,),
        )
    assert (
        a.post(
            "/api/v1/projects",
            json={"client_request_id": str(uuid4()), "name": "Over limit"},
        ).status_code
        == 429
    )
    assert (
        a.post(
            "/api/v1/me/saved-prompts",
            json={
                "client_request_id": str(uuid4()),
                "label": "Over limit",
                "prompt": "No",
            },
        ).status_code
        == 429
    )
    assert world.calls == []


def test_workspace_changes_do_not_wait_for_password_admission_bookkeeping(world):
    a, _ = world.client(grant=False)
    with psycopg.connect(RUNTIME, autocommit=True, connect_timeout=2) as connection:
        with connection.transaction():
            connection.execute(
                "SELECT pg_advisory_xact_lock(%s)", (PASSWORD_ADMISSION_LOCK,)
            )
            response = a.post(
                "/api/v1/me/saved-prompts",
                json={
                    "client_request_id": str(uuid4()),
                    "label": "Independent",
                    "prompt": "Keep account actions available",
                },
            )
            assert response.status_code == 201, response.text
    assert world.calls == []
