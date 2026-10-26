"""Stable keysets, bounded prefix search and fixed-query recent summaries."""


def test_keyset_ties_deep_pages_filter_binding_and_literal_wildcards(world):
    a, owner = world.client()
    with world.storage.transaction() as conn:
        for number in range(85):
            conn.execute(
                "INSERT INTO app.chats(user_id,title,last_activity_at) VALUES(%s,%s,'2026-10-26T12:00:00Z')",
                (owner, f"Loan {number:03d}"),
            )
        conn.execute(
            "INSERT INTO app.chats(user_id,title) VALUES(%s,'100%% literal')", (owner,)
        )
    seen, cursor = [], None
    for _ in range(6):
        page = a.post(
            "/api/v1/chats/search",
            json={
                "limit": 20,
                "search": "Loan",
                **({"cursor": cursor} if cursor else {}),
            },
        ).json()
        seen.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == 85
    first = a.post("/api/v1/chats/search", json={"limit": 1, "search": "Loan"}).json()
    assert (
        a.post(
            "/api/v1/chats/search",
            json={"cursor": first["next_cursor"], "search": "Other"},
        ).status_code
        == 422
    )
    assert (
        len(a.post("/api/v1/chats/search", json={"search": "100%"}).json()["items"])
        == 1
    )
    assert a.post("/api/v1/chats/search", json={"search": "%"}).json()["items"] == []
    assert (
        a.post("/api/v1/chats/search", json={"search": "No matches"}).json()["items"]
        == []
    )
    assert a.post("/api/v1/chats/search", json={"search": "x" * 81}).status_code == 422
    assert a.get("/api/v1/chats?limit=101").status_code == 422

    assert a.get("/api/v1/chats", params={"search": "Private query"}).status_code == 422


def test_latest_messages_arrive_in_order_and_older_pages_do_not_fetch_everything(world):
    a, _ = world.client()
    saved = world.submit(a, "First question")
    chat_id = saved["chat"]["id"]
    for number in range(4):
        assert (
            a.post(
                f"/api/v1/chats/{chat_id}/messages",
                json=world.body(f"Question {number}"),
            ).status_code
            == 200
        )
    page = a.get(f"/api/v1/chats/{chat_id}/messages?limit=3").json()
    assert [item["sequence"] for item in page["items"]] == [8, 9, 10]
    seen = [item["id"] for item in page["items"]]
    while page["older_cursor"]:
        page = a.get(
            f"/api/v1/chats/{chat_id}/messages",
            params={"limit": 3, "cursor": page["older_cursor"]},
        ).json()
        assert [item["sequence"] for item in page["items"]] == sorted(
            item["sequence"] for item in page["items"]
        )
        seen.extend(item["id"] for item in page["items"])
    assert len(seen) == len(set(seen)) == 10
    other = world.submit(a)
    cursor = a.get(f"/api/v1/chats/{chat_id}/messages?limit=1").json()["older_cursor"]
    assert (
        a.get(
            f"/api/v1/chats/{other['chat']['id']}/messages", params={"cursor": cursor}
        ).status_code
        == 422
    )


def test_search_text_stays_in_json_body_and_requires_same_origin_csrf(world, caplog):
    a, _ = world.client(grant=False)
    canary = "PRIVATE_SEARCH_BODY_CANARY"
    response = a.post("/api/v1/chats/search", json={"search": canary})
    assert response.status_code == 200 and canary not in str(response.request.url)
    assert canary not in caplog.text and world.calls == []
    for headers in [{"X-CSRF-Token": "wrong"}, {"Origin": "https://evil.invalid"}]:
        assert (
            a.post(
                "/api/v1/chats/search", json={"search": canary}, headers=headers
            ).status_code
            == 403
        )
