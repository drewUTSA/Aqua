"""Additive schema/history compatibility and bounded abandoned-request recovery."""

from pathlib import Path


from storage.migrate import apply, migrations


def test_schema3_backup_accepts_conditional_workspace_restore_fence(app_database):
    assert apply(app_database, migrations()[:3]) == 3
    fence = Path(__file__).resolve().parents[2] / "ops/appdb/restore_session_fence.sql"
    app_database.execute(fence.read_text())
    app_database.execute("SET ROLE aqua_app_owner")
    assert app_database.execute(
        "SELECT to_regclass('app.analysis_requests')"
    ).fetchone() == (None,)
    app_database.execute("RESET ROLE")
    assert apply(app_database) == 5


def test_old_pending_record_retires_without_new_model_call_or_double_refund(
    world, monkeypatch
):
    from workspace import completion
    from workspace.database import guard
    from workspace.contracts import FirstSubmission
    from workspace import submissions
    from auth.security import UserSession
    from auth.sessions import token_digest, read_token, session_cookie_name

    a, owner = world.client()
    raw = read_token(a.cookies.get(session_cookie_name(world.settings)))
    stored = world.store.authenticate(token_digest(raw))
    session = UserSession(
        stored.user,
        "",
        token_digest(raw),
        True,
        stored.grant_version,
        stored.auth_epoch,
        stored.dataset_key,
    )
    body = FirstSubmission.model_validate(world.body("Unfinished request"))
    with world.storage.transaction() as conn:
        guard(conn, session, world.policy, mutate=True, data=True)
        request_id, created = submissions.begin(
            conn, session, body, chat_id=None, input_id=None, default_model="ollama"
        )
        assert created
        conn.execute(
            "UPDATE app.analysis_requests SET created_at=now()-interval '3 hours' WHERE id=%s",
            (request_id,),
        )
    first = a.get("/api/v1/chats").json()["items"][0]
    page = a.get(f"/api/v1/chats/{first['id']}/messages").json()["items"]
    assert page[-1]["status"] == "interrupted" and world.calls == []
    with world.storage.transaction() as conn:
        before = conn.execute(
            "SELECT content_bytes FROM app.workspace_usage WHERE user_id=%s", (owner,)
        ).fetchone()[0]
        completion.interrupt(conn, owner, request_id)
        assert (
            conn.execute(
                "SELECT content_bytes FROM app.workspace_usage WHERE user_id=%s",
                (owner,),
            ).fetchone()[0]
            == before
        )
        completion.finish(
            conn, session, request_id, {"status": "success", "message": "Late result"}
        )
        assert conn.execute(
            "SELECT count(*) FROM app.visual_results WHERE request_id=%s", (request_id,)
        ).fetchone() == (0,)
