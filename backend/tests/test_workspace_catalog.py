"""Project/prompt ownership, revisions, usage replay and normal recovery."""

from uuid import uuid4


def test_project_crud_foreign_assignment_archive_and_detach_preserve_chat(world):
    a, _ = world.client("A")
    b, _ = world.client("B")
    key = {"client_request_id": str(uuid4()), "name": "Analysis"}
    first = a.post("/api/v1/projects", json=key).json()["project"]
    assert a.post("/api/v1/projects", json=key).json()["project"] == first
    assert (
        a.post("/api/v1/projects", json={**key, "name": "Changed"}).status_code == 409
    )
    assert (
        b.post("/api/v1/chats", json=world.body(project_id=first["id"])).status_code
        == 404
    )
    saved = a.post("/api/v1/chats", json=world.body(project_id=first["id"])).json()
    assert saved["chat"]["project_id"] == first["id"]
    assert (
        b.patch(
            f"/api/v1/projects/{first['id']}", json={"revision": 1, "name": "Steal"}
        ).status_code
        == 404
    )
    assert (
        a.patch(
            f"/api/v1/projects/{first['id']}", json={"revision": 9, "name": "Stale"}
        ).status_code
        == 409
    )
    updated = a.patch(
        f"/api/v1/projects/{first['id']}",
        json={"revision": 1, "name": "Renamed", "archived": True},
    ).json()["project"]
    assert updated["revision"] == 2 and a.get("/api/v1/projects").json()["items"] == []
    assert (
        a.get("/api/v1/projects?archived=true").json()["items"][0]["name"] == "Renamed"
    )
    assert a.delete(f"/api/v1/projects/{first['id']}?revision=2").status_code == 204
    assert a.post("/api/v1/projects", json=key).status_code == 404
    assert (
        a.post(
            "/api/v1/projects",
            json={"client_request_id": str(uuid4()), "name": "Fresh group"},
        ).status_code
        == 201
    )
    chat = a.get(f"/api/v1/chats/{saved['chat']['id']}").json()["chat"]
    assert chat["project_id"] is None and chat["message_count"] == 2
    with world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT fingerprint=decode(repeat('00',32),'hex') FROM app.projects WHERE id=%s",
            (first["id"],),
        ).fetchone() == (True,)


def test_saved_prompt_private_crud_pin_usage_replay_and_curated_catalog(world):
    a, _ = world.client("A", grant=False)
    b, _ = world.client("B", grant=False)
    body = {
        "client_request_id": str(uuid4()),
        "label": "<img onerror=alert(1)>",
        "prompt": "=1+1; DROP TABLE app.users",
        "pinned": True,
    }
    prompt = a.post("/api/v1/me/saved-prompts", json=body).json()["saved_prompt"]
    assert prompt["prompt"] == body["prompt"] and prompt["pinned"]
    assert b.get("/api/v1/me/saved-prompts").json()["items"] == []
    assert (
        b.patch(
            f"/api/v1/me/saved-prompts/{prompt['id']}",
            json={"revision": 1, "pinned": False},
        ).status_code
        == 404
    )
    assert (
        a.post("/api/v1/me/saved-prompts", json=body).json()["saved_prompt"] == prompt
    )
    use = {"client_request_id": str(uuid4())}
    path = f"/api/v1/me/saved-prompts/{prompt['id']}/uses"
    first = a.post(path, json=use).json()["saved_prompt"]
    assert first["use_count"] == 1
    assert a.post(path, json=use).json()["saved_prompt"]["use_count"] == 1
    changed = a.patch(
        f"/api/v1/me/saved-prompts/{prompt['id']}",
        json={
            "revision": first["revision"],
            "label": "Personal",
            "prompt": "New prompt",
            "pinned": False,
        },
    ).json()["saved_prompt"]
    assert changed["prompt"] == "New prompt" and not changed["pinned"]
    starters = a.get("/api/v1/starter-prompts").json()["items"]
    assert len(starters) == 4 and all(
        item["prompt"] != body["prompt"] for item in starters
    )
    assert (
        a.delete(
            f"/api/v1/me/saved-prompts/{prompt['id']}?revision={changed['revision']}"
        ).status_code
        == 204
    )
    assert a.get("/api/v1/me/saved-prompts").json()["items"] == [] and world.calls == []
    assert a.post("/api/v1/me/saved-prompts", json=body).status_code == 404
    assert a.post(path, json=use).status_code == 404
    with world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT fingerprint=decode(repeat('00',32),'hex') FROM app.saved_prompts WHERE id=%s",
            (prompt["id"],),
        ).fetchone() == (True,)
    assert (
        a.post(
            "/api/v1/me/saved-prompts",
            json={
                "client_request_id": str(uuid4()),
                "label": "Fresh",
                "prompt": "Fresh prompt",
            },
        ).status_code
        == 201
    )


def test_chat_revision_archive_delete_erases_payload_and_prevents_replay_recreation(
    world,
):
    a, owner = world.client()
    body = world.body("A private chat")
    saved = a.post("/api/v1/chats", json=body).json()
    chat_id = saved["chat"]["id"]
    path = f"/api/v1/chats/{chat_id}"
    assert a.patch(path, json={"revision": 1, "title": "Stale"}).status_code == 409
    changed = a.patch(
        path, json={"revision": 2, "title": "Renamed", "archived": True}
    ).json()["chat"]
    assert a.get("/api/v1/chats").json()["items"] == []
    assert a.get("/api/v1/chats?archived=true").json()["items"][0]["title"] == "Renamed"
    assert a.post(path + "/messages", json=world.body()).status_code == 409
    unarchived = a.patch(
        path, json={"revision": changed["revision"], "archived": False}
    ).json()["chat"]
    assert a.delete(path + f"?revision={unarchived['revision']}").status_code == 204
    assert a.get(path).status_code == 404
    assert a.get(path + "/messages").status_code == 404
    assert a.post("/api/v1/chats", json=body).status_code == 404
    with world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT bool_and(fingerprint=decode(repeat('00',32),'hex')) FROM app.analysis_requests WHERE user_id=%s",
            (owner,),
        ).fetchone() == (True,)
        assert conn.execute(
            "SELECT count(*) FROM app.visual_results WHERE user_id=%s", (owner,)
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM app.messages WHERE user_id=%s AND content<>''",
            (owner,),
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT content_bytes FROM app.workspace_usage WHERE user_id=%s", (owner,)
        ).fetchone() == (0,)
