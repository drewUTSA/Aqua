"""Original-lease cleanup must never alter a newer execution's reservation."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from workspace.contracts import FirstSubmission


@pytest.mark.parametrize("new_state", ["running", "cancelling"])
def test_late_old_attempt_cannot_terminate_or_refund_a_newer_lease(security, new_state):
    service = security.service()
    _, session = security.session()
    saved, _ = service.enqueue(session, FirstSubmission(**security.world.body()))
    request_id = saved["request"]["id"]
    security.engine.release.clear()
    original = security.engine.run
    security.engine.run = lambda payload, control: original(
        payload, lambda stage=None: None
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        old_attempt = pool.submit(service.tick)
        try:
            security.engine.wait_active(1)
            new_owner = str(uuid4())
            with security.storage.transaction() as conn:
                # Simulate a future legitimate takeover without making a second
                # external call. Its token/physical reservation must be sovereign.
                conn.execute(
                    "UPDATE app.analysis_jobs SET lease_token=lease_token+1,lease_owner=%s,"
                    "state=%s,cancel_requested=%s,lease_until=clock_timestamp()+interval '15 seconds',"
                    "physical_until=deadline_at+interval '5 seconds' WHERE id=%s",
                    (new_owner, new_state, new_state == "cancelling", request_id),
                )
                conn.execute(
                    "UPDATE app.analysis_requests SET state=%s WHERE id=%s",
                    (new_state, request_id),
                )
                before = conn.execute(
                    "SELECT state,lease_token,lease_owner,physical_until,content_bytes "
                    "FROM app.analysis_jobs WHERE id=%s",
                    (request_id,),
                ).fetchone()
                usage = conn.execute(
                    "SELECT content_bytes FROM app.workspace_usage WHERE user_id=%s",
                    (session.user["id"],),
                ).fetchone()
        finally:
            security.engine.release.set()
        assert old_attempt.result(timeout=3)
    with security.storage.transaction() as conn:
        assert (
            conn.execute(
                "SELECT state,lease_token,lease_owner,physical_until,content_bytes "
                "FROM app.analysis_jobs WHERE id=%s",
                (request_id,),
            ).fetchone()
            == before
        )
        assert (
            conn.execute(
                "SELECT content_bytes FROM app.workspace_usage WHERE user_id=%s",
                (session.user["id"],),
            ).fetchone()
            == usage
        )
        assert conn.execute("SELECT count(*) FROM app.visual_results").fetchone() == (
            0,
        )
        assert conn.execute(
            "SELECT state,reserved_bytes FROM app.analysis_requests WHERE id=%s",
            (request_id,),
        ).fetchone() == (new_state, 1024)
    assert len(security.engine.calls) == 1 and security.engine.active == 0


def test_expired_queued_request_never_calls_engine_and_refunds_once(security):
    service = security.service()
    _, session = security.session()
    saved, _ = service.enqueue(session, FirstSubmission(**security.world.body()))
    request_id = saved["request"]["id"]
    with security.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.analysis_jobs SET created_at=now()-interval '121 seconds',"
            "deadline_at=now()-interval '1 second' WHERE id=%s",
            (request_id,),
        )
    assert not service.tick()
    with security.storage.transaction() as conn:
        first = conn.execute(
            "SELECT content_bytes FROM app.workspace_usage WHERE user_id=%s",
            (session.user["id"],),
        ).fetchone()
        assert conn.execute(
            "SELECT state,reserved_bytes FROM app.analysis_requests WHERE id=%s",
            (request_id,),
        ).fetchone() == ("expired", 0)
    service.dispatch.housekeeping()
    with security.storage.transaction() as conn:
        assert (
            conn.execute(
                "SELECT content_bytes FROM app.workspace_usage WHERE user_id=%s",
                (session.user["id"],),
            ).fetchone()
            == first
        )
    assert security.engine.calls == []
