"""Live-session metadata stays bounded despite retained expired history."""

from uuid import uuid4

from account.repository import LIVE_SESSIONS_SQL


def test_session_list_filters_owner_epoch_revocation_and_expiry(world):
    a, owner = world.client(grant=False)
    world.client(grant=False)
    b, other = world.client("B", grant=False)
    with world.storage.transaction() as conn:
        for epoch, revoked, lifetime in [
            (0, True, 60),
            (0, False, -60),
            (1, False, 60),
        ]:
            conn.execute(
                "INSERT INTO app.sessions(user_id,token_digest,csrf_digest,auth_epoch,method,"
                "created_at,idle_expires_at,absolute_expires_at,revoked_at) "
                "VALUES(%s,%s,%s,%s,'password',now()-interval '2 hours',"
                "now()+%s*interval '1 second',now()+interval '1 hour',%s)",
                (
                    owner,
                    uuid4().bytes * 2,
                    uuid4().bytes * 2,
                    epoch,
                    lifetime,
                    conn.execute("SELECT now()").fetchone()[0] if revoked else None,
                ),
            )
        own_ids = {
            str(row[0])
            for row in conn.execute(
                "SELECT id FROM app.sessions WHERE user_id=%s AND auth_epoch=0 "
                "AND revoked_at IS NULL AND idle_expires_at>now()",
                (owner,),
            ).fetchall()
        }
        foreign_ids = {
            str(row[0])
            for row in conn.execute(
                "SELECT id FROM app.sessions WHERE user_id=%s", (other,)
            ).fetchall()
        }
    listed = a.get("/api/v1/me/sessions").json()["items"]
    assert {item["id"] for item in listed} == own_ids
    assert not own_ids & foreign_ids
    assert len(listed) == 2 and sum(item["current"] for item in listed) == 1
    assert listed[0]["current"] is True
    assert len(b.get("/api/v1/me/sessions").json()["items"]) == 1


def test_session_list_uses_live_owner_index_with_large_expired_history(
    world, app_database
):
    a, owner = world.client(grant=False)
    with world.storage.transaction() as conn:
        conn.execute(
            "INSERT INTO app.sessions(user_id,token_digest,csrf_digest,auth_epoch,method,"
            "created_at,idle_expires_at,absolute_expires_at) "
            "SELECT %s,decode(md5('p10-expired-'||n::text)||md5('p10-tail-'||n::text),'hex'),"
            "%s,0,'google',now()-interval '2 hours',now()-interval '1 hour',"
            "now()+interval '1 hour' FROM generate_series(1,5000) n",
            (owner, uuid4().bytes * 2),
        )
    app_database.execute("SET ROLE aqua_app_owner")
    app_database.execute("ANALYZE app.sessions")
    app_database.execute("RESET ROLE")
    response = a.get("/api/v1/me/sessions")
    assert response.status_code == 200 and len(response.json()["items"]) == 1
    with world.storage.transaction() as conn:
        instant = conn.execute("SELECT clock_timestamp()").fetchone()[0]
        plan = conn.execute(
            "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + LIVE_SESSIONS_SQL,
            (owner, 0, instant, instant, 21),
        ).fetchone()[0][0]["Plan"]

    def nodes(node):
        yield node
        for child in node.get("Plans", []):
            yield from nodes(child)

    assert plan["Actual Rows"] == 1
    assert any(
        node.get("Index Name") == "sessions_owner_epoch_idle" for node in nodes(plan)
    )
    assert plan.get("Shared Hit Blocks", 0) + plan.get("Shared Read Blocks", 0) <= 64


def test_corrupt_unbounded_live_set_is_not_silently_truncated(world):
    a, owner = world.client(grant=False)
    with world.storage.transaction() as conn:
        conn.execute(
            "INSERT INTO app.sessions(user_id,token_digest,csrf_digest,auth_epoch,method,"
            "idle_expires_at,absolute_expires_at) SELECT %s,"
            "decode(md5('p10-live-'||n::text)||md5('p10-live-tail-'||n::text),'hex'),"
            "%s,0,'google',now()+interval '5 minutes',now()+interval '1 hour' "
            "FROM generate_series(1,20) n",
            (owner, uuid4().bytes * 2),
        )
    response = a.get("/api/v1/me/sessions")
    assert response.status_code == 503
    assert "items" not in response.json()
