"""Cross-service queue/running bounds and durable session-churn accounting."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from analysis import policy
from workspace.contracts import FirstSubmission
from workspace.errors import WorkspaceError


def enqueue(security, service, session, question="One bounded request"):
    return service.enqueue(session, FirstSubmission(**security.world.body(question)))


def test_distinct_service_instances_share_running_queue_and_replay_capacity(security):
    security.engine.release.clear()
    services = [security.service() for _ in range(policy.RUNNING_GLOBAL)]
    queuer, probe = security.service(), security.service()
    sessions = [
        security.session(f"Owner-{number}")[1]
        for number in range(policy.RUNNING_GLOBAL + policy.QUEUED_GLOBAL + 1)
    ]
    for number, service in enumerate(services):
        assert enqueue(security, service, sessions[number])[1] == 202
    with ThreadPoolExecutor(max_workers=policy.RUNNING_GLOBAL) as pool:
        running = [pool.submit(service.tick) for service in services]
        try:
            security.engine.wait_active(policy.RUNNING_GLOBAL)
            queued = []
            for session in sessions[policy.RUNNING_GLOBAL : -1]:
                body = FirstSubmission(**security.world.body())
                saved, status = queuer.enqueue(session, body)
                assert status == 202
                queued.append((session, body, saved))
            with pytest.raises(WorkspaceError) as denied:
                enqueue(security, queuer, sessions[-1])
            assert denied.value.status == 429
            session, body, saved = queued[-1]
            replay, status = queuer.enqueue(session, body)
            assert status == 202 and replay["request"]["id"] == saved["request"]["id"]
            with pytest.raises(WorkspaceError) as conflict:
                queuer.enqueue(
                    session,
                    body.model_copy(update={"question": "Changed after acceptance"}),
                )
            assert conflict.value.status == 409
            with security.storage.transaction() as conn:
                assert conn.execute(
                    "SELECT count(*) FROM app.analysis_jobs"
                ).fetchone() == (policy.RUNNING_GLOBAL + policy.QUEUED_GLOBAL,)
                assert conn.execute("SELECT count(*) FROM app.messages").fetchone() == (
                    2 * (policy.RUNNING_GLOBAL + policy.QUEUED_GLOBAL),
                )
            assert not probe.tick()
            assert security.engine.maximum == policy.RUNNING_GLOBAL
        finally:
            security.engine.release.set()
        assert all(task.result(timeout=3) for task in running)


def test_cancel_releases_queue_but_never_refunds_provider_budget_across_sessions(
    security,
):
    service = security.service()
    accepted = []
    for number in range(3):
        _, session = security.session("Same-owner")
        saved, status = enqueue(security, service, session, f"Accepted {number}")
        assert status == 202
        accepted.append(saved["request"]["id"])
        cancelled, _ = service.cancel(session, saved["request"]["id"])
        assert cancelled["request"]["state"] == "cancelled"
    _, another_session = security.session("Same-owner")
    with pytest.raises(WorkspaceError) as denied:
        enqueue(
            security, service, another_session, "Fresh cookie cannot mint more budget"
        )
    assert denied.value.status == 429
    assert denied.value.code == "analysis_rate_limited"
    assert security.engine.calls == []
    with security.storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.analysis_jobs").fetchone() == (3,)
        assert conn.execute(
            "SELECT count(*) FROM app.analysis_requests WHERE reserved_bytes<>0"
        ).fetchone() == (0,)


def test_no_grant_account_cannot_enqueue_or_spend_analytical_capacity(security):
    service = security.service()
    _, session = security.session("No-grant", grant=False)
    with pytest.raises(WorkspaceError) as denied:
        enqueue(security, service, session)
    assert denied.value.status == 403
    assert security.engine.calls == []
    with security.storage.transaction() as conn:
        for table in ("analysis_jobs", "analysis_requests", "analysis_admission"):
            assert conn.execute(f"SELECT count(*) FROM app.{table}").fetchone() == (0,)


def test_legacy_http_route_cannot_bypass_budget_spent_through_durable_routes(
    security, monkeypatch
):
    import main

    service = security.service()
    client, session = security.session()
    monkeypatch.setattr(main.app.state, "storage", service.storage)
    monkeypatch.setattr(main.app.state, "analysis", service, raising=False)
    for number in range(3):
        saved, _ = enqueue(security, service, session, f"Budgeted {number}")
        service.cancel(session, saved["request"]["id"])
    denied = client.post(
        "/api/query", json={"question": "Legacy bypass", "model": "ollama"}
    )
    assert denied.status_code == 429, denied.text
    assert denied.json()["error"]["code"] == "analysis_rate_limited"
    assert security.engine.calls == []
    with security.storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.analysis_jobs").fetchone() == (3,)
        assert conn.execute("SELECT count(*) FROM app.chats").fetchone() == (3,)


def test_legacy_success_keeps_original_json_and_never_creates_hidden_chat(
    security, monkeypatch
):
    import main
    from workspace_fixtures import GOOD

    service = security.service()
    client, _ = security.session()
    monkeypatch.setattr(main.app.state, "storage", service.storage)
    monkeypatch.setattr(main.app.state, "analysis", service, raising=False)
    reply = client.post(
        "/api/query", json={"question": "One legacy answer", "model": "ollama"}
    )
    assert reply.status_code == 200 and reply.json() == GOOD
    assert len(security.engine.calls) == 1
    with security.storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.chats").fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM app.analysis_requests"
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM app.analysis_jobs WHERE request_id IS NULL"
        ).fetchone() == (1,)


@pytest.mark.parametrize("operation,maximum", [("read", 120), ("cancel", 60)])
def test_failed_foreign_ids_spend_shared_observation_budget_without_blocking_other_operation(
    security, operation, maximum
):
    service = security.service()
    _, session = security.session("Observer")
    own, _ = enqueue(security, service, session)
    _, foreign_session = security.session("Foreign")
    foreign, _ = enqueue(security, service, foreign_session)
    owner = session.user["id"]
    scopes = [operation + ":account:" + owner, operation + ":global"]
    with security.storage.transaction() as conn:
        for scope in scopes:
            conn.execute(
                "INSERT INTO app.analysis_admission(scope,units,expires_at) "
                "VALUES(%s,%s,clock_timestamp()+interval '1 minute')",
                (scope, maximum - 1),
            )
        ai_before = conn.execute(
            "SELECT scope,units FROM app.analysis_admission "
            "WHERE scope NOT LIKE 'read:%' AND scope NOT LIKE 'cancel:%' "
            "ORDER BY scope"
        ).fetchall()
    invoke = service.snapshot if operation == "read" else service.cancel
    with pytest.raises(WorkspaceError) as missing:
        invoke(session, foreign["request"]["id"])
    assert missing.value.status == 404
    # Item lookup fails after the observation transaction commits. A new
    # session cannot roll back the charge or mint another allowance.
    _, fresh_session = security.session("Observer")
    with pytest.raises(WorkspaceError) as limited:
        invoke(fresh_session, own["request"]["id"])
    assert limited.value.status == 429
    with pytest.raises(WorkspaceError) as globally_limited:
        invoke(foreign_session, foreign["request"]["id"])
    assert globally_limited.value.status == 429
    # Read exhaustion must leave cancellation available, and vice versa.
    if operation == "read":
        assert (
            service.cancel(fresh_session, own["request"]["id"])[0]["request"]["state"]
            == "cancelled"
        )
    else:
        assert (
            service.snapshot(fresh_session, own["request"]["id"])["request"]["state"]
            == "queued"
        )
    with security.storage.transaction() as conn:
        assert conn.execute(
            "SELECT units FROM app.analysis_admission WHERE scope=ANY(%s)",
            (scopes,),
        ).fetchall() == [(maximum,), (maximum,)]
        assert (
            conn.execute(
                "SELECT scope,units FROM app.analysis_admission "
                "WHERE scope NOT LIKE 'read:%' AND scope NOT LIKE 'cancel:%' "
                "ORDER BY scope"
            ).fetchall()
            == ai_before
        )
    assert security.engine.calls == []
