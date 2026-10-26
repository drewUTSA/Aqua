"""Composite database ownership and indexed bounded-list query plans."""

from uuid import uuid4

import pytest

from storage.pool import StorageUnavailable


def test_database_rejects_foreign_project_message_and_result_parents(world):
    a, a_id = world.client("A")
    b, b_id = world.client("B")
    saved = world.submit(a)
    project = b.post(
        "/api/v1/projects", json={"client_request_id": str(uuid4()), "name": "B only"}
    ).json()["project"]
    cases = [
        (
            "INSERT INTO app.chats(user_id,project_id,title) VALUES(%s,%s,'Foreign parent')",
            (a_id, project["id"]),
        ),
        (
            "INSERT INTO app.messages(user_id,chat_id,sequence,role,status) VALUES(%s,%s,99,'aqua','pending')",
            (b_id, saved["chat"]["id"]),
        ),
        (
            "INSERT INTO app.visual_results(user_id,chat_id,request_id,response) VALUES(%s,%s,%s,'{}')",
            (b_id, saved["chat"]["id"], saved["request"]["id"]),
        ),
    ]
    for statement, params in cases:
        with pytest.raises(StorageUnavailable):
            with world.storage.transaction() as conn:
                conn.execute(statement, params)
    assert b.get("/api/v1/chats").json()["items"] == []
    assert (
        len(a.get(f"/api/v1/chats/{saved['chat']['id']}/messages").json()["items"]) == 2
    )


def test_representative_title_and_recents_plans_seek_owner_indexes(world, app_database):
    a, owner = world.client()
    with world.storage.transaction() as conn:
        # 100 valid-sized private workspaces establish realistic selectivity.
        others = [
            conn.execute(
                "INSERT INTO app.users(status) VALUES('active') RETURNING id"
            ).fetchone()[0]
            for _ in range(100)
        ]
        for other in others:
            conn.execute(
                "INSERT INTO app.chats(user_id,title) SELECT %s,'Other '||n FROM generate_series(1,50) n",
                (other,),
            )
        conn.execute(
            "INSERT INTO app.chats(user_id,title) SELECT %s,'Loan '||n FROM generate_series(1,80) n",
            (owner,),
        )
    app_database.execute("SET ROLE aqua_app_owner")
    app_database.execute("ANALYZE app.chats")
    app_database.execute("RESET ROLE")
    with world.storage.transaction() as conn:
        plan = conn.execute(
            "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) SELECT id,title,last_activity_at FROM app.chats WHERE user_id=%s AND deleted_at IS NULL AND archived=false AND lower(title) LIKE 'loan%%' ORDER BY last_activity_at DESC,id DESC LIMIT 20",
            (owner,),
        ).fetchone()[0][0]["Plan"]

    def nodes(node):
        yield node
        for child in node.get("Plans", []):
            yield from nodes(child)

    indexes = {node.get("Index Name") for node in nodes(plan)}
    assert indexes & {
        "chats_owner_activity",
        "chats_owner_title",
        "chats_owner_project",
    }, plan
    assert plan["Actual Rows"] == 20
    assert (
        len(a.post("/api/v1/chats/search", json={"search": "Loan"}).json()["items"])
        == 20
    )
