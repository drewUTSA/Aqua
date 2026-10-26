"""Direct real-session red/blue checks over disposable private PostgreSQL."""

from uuid import uuid4

import pytest

from workspace_fixtures import GOOD


def test_atomic_first_submit_replay_conflict_and_restart_history(world):
    a, owner = world.client()
    body = world.body("Loan count")
    first = a.post("/api/v1/chats", json=body)
    assert first.status_code == 201, first.text
    saved = first.json()
    repeat = a.post("/api/v1/chats", json=body)
    assert repeat.status_code == 200 and repeat.json() == saved
    conflict = a.post("/api/v1/chats", json={**body, "question": "Different"})
    assert conflict.status_code == 409 and len(world.calls) == 1
    another, same_owner = world.client()
    assert same_owner == owner
    recent = another.get("/api/v1/chats").json()["items"]
    assert recent[0]["id"] == saved["chat"]["id"] and recent[0]["message_count"] == 2
    messages = another.get(f"/api/v1/chats/{recent[0]['id']}/messages").json()["items"]
    assert [m["sequence"] for m in messages] == [1, 2]
    assert messages[0]["response"] is None and messages[1]["response"] == GOOD


def test_two_user_lists_ids_childlinks_and_foreign_cursors_are_isolated(world):
    a, _ = world.client("A")
    b, _ = world.client("B")
    saved = world.submit(a)
    world.submit(a, "Another title")
    chat_id = saved["chat"]["id"]
    assert b.get("/api/v1/chats").json()["items"] == []
    assert (
        b.post("/api/v1/chats/search", json={"search": "Count"}).json()["items"] == []
    )
    for path in [f"/api/v1/chats/{chat_id}", f"/api/v1/chats/{chat_id}/messages"]:
        assert b.get(path).status_code == 404
    assert (
        b.patch(
            f"/api/v1/chats/{chat_id}", json={"revision": 2, "title": "Stolen"}
        ).status_code
        == 404
    )
    assert b.delete(f"/api/v1/chats/{chat_id}?revision=2").status_code == 404
    assert (
        b.post(f"/api/v1/chats/{chat_id}/messages", json=world.body()).status_code
        == 404
    )
    token = a.get("/api/v1/chats?limit=1").json()["next_cursor"]
    assert token and b.get("/api/v1/chats", params={"cursor": token}).status_code == 422
    assert len(world.calls) == 2


def test_no_dataset_account_can_save_prompts_and_projects_but_not_query(world):
    a, owner = world.client(grant=False)
    project = a.post(
        "/api/v1/projects",
        json={"client_request_id": str(uuid4()), "name": "Private project"},
    )
    prompt = a.post(
        "/api/v1/me/saved-prompts",
        json={
            "client_request_id": str(uuid4()),
            "label": "Personal",
            "prompt": "A private draft",
        },
    )
    assert project.status_code == prompt.status_code == 201
    assert a.post("/api/v1/chats", json=world.body()).status_code == 403
    assert world.calls == []
    with world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.chats WHERE user_id=%s", (owner,)
        ).fetchone() == (0,)


@pytest.mark.parametrize("change", ["revoked", "epoch", "disabled", "expired"])
def test_current_session_and_account_state_denies_workspace_mutations(world, change):
    a, owner = world.client()
    with world.storage.transaction() as conn:
        if change == "revoked":
            conn.execute(
                "UPDATE app.sessions SET revoked_at=clock_timestamp() WHERE user_id=%s",
                (owner,),
            )
        elif change == "epoch":
            conn.execute(
                "UPDATE app.users SET auth_epoch=auth_epoch+1 WHERE id=%s", (owner,)
            )
        elif change == "disabled":
            conn.execute("UPDATE app.users SET status='disabled' WHERE id=%s", (owner,))
        else:
            conn.execute(
                "UPDATE app.sessions SET created_at=now()-interval '2 hours',idle_expires_at=now()-interval '1 hour',absolute_expires_at=now()-interval '30 minutes' WHERE user_id=%s",
                (owner,),
            )
    response = a.post("/api/v1/chats", json=world.body())
    assert response.status_code == 401 and world.calls == []


def test_missing_csrf_origin_and_mass_assignment_do_no_unauthorized_work(world):
    a, _ = world.client()
    for headers in [{"Origin": "https://evil.invalid"}, {"X-CSRF-Token": "wrong"}]:
        assert (
            a.post("/api/v1/chats", json=world.body(), headers=headers).status_code
            == 403
        )
    for field in ["owner_id", "response", "sql", "user_id"]:
        assert (
            a.post("/api/v1/chats", json=world.body(**{field: "forged"})).status_code
            == 422
        )
    assert world.calls == []


def test_revoked_grant_withholds_all_historical_assistant_content(world):
    a, owner = world.client()
    saved = world.submit(a)
    with world.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.dataset_grants SET revoked_at=clock_timestamp() WHERE user_id=%s",
            (owner,),
        )
    page = a.get(f"/api/v1/chats/{saved['chat']['id']}/messages")
    assert page.status_code == 200
    assert GOOD["message"] not in page.text and GOOD["sql"] not in page.text
    messages = page.json()["items"]
    assert messages[0]["response"] is None
    assert messages[1]["result_unavailable"] and messages[1]["response"] is None
    assert a.post("/api/v1/chats", json=world.body()).status_code == 403
