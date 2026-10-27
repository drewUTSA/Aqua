"""Late or uncooperative work cannot undo cancellation, deletion or revocation."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from analysis import policy
from workspace.contracts import FirstSubmission


def accepted(security, service, session, question="Hold this request"):
    saved, status = service.enqueue(
        session, FirstSubmission(**security.world.body(question))
    )
    assert status == 202
    return saved


@pytest.mark.parametrize("race", ["cancel", "revoke", "logout", "delete", "regrant"])
def test_uncooperative_final_response_cannot_commit_after_security_race(security, race):
    service = security.service()
    client, session = security.session()
    saved = accepted(security, service, session)
    request_id = saved["request"]["id"]
    observed = []

    def change_authority():
        if race == "cancel":
            snapshot, status = service.cancel(session, request_id)
            observed.append((snapshot["request"]["state"], status))
        elif race == "delete":
            observed.append(
                client.delete(
                    f"/api/v1/chats/{saved['chat']['id']}?revision={saved['chat']['revision']}"
                ).status_code
            )
        else:
            with security.storage.transaction() as conn:
                if race == "logout":
                    conn.execute(
                        "UPDATE app.sessions SET revoked_at=clock_timestamp() WHERE token_digest=%s",
                        (session.token_digest,),
                    )
                elif race == "revoke":
                    conn.execute(
                        "UPDATE app.dataset_grants SET revoked_at=clock_timestamp() WHERE user_id=%s",
                        (session.user["id"],),
                    )
                else:
                    conn.execute(
                        "UPDATE app.dataset_grants SET version=version+1 WHERE user_id=%s",
                        (session.user["id"],),
                    )

    security.engine.hook = change_authority
    assert service.tick()
    assert len(security.engine.calls) == 1
    if race == "cancel":
        assert observed == [("cancelling", 202)]
    if race == "delete":
        assert observed == [204]
    with security.storage.transaction() as conn:
        state, reserved = conn.execute(
            "SELECT state,reserved_bytes FROM app.analysis_requests WHERE id=%s",
            (request_id,),
        ).fetchone()
        assert state == ("cancelled" if race == "cancel" else "interrupted")
        assert reserved == 0
        assert conn.execute(
            "SELECT count(*) FROM app.visual_results WHERE request_id=%s", (request_id,)
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT question,context,content_bytes,physical_until FROM app.analysis_jobs WHERE id=%s",
            (request_id,),
        ).fetchone() == ("", [], 0, None)


def test_cancelled_queued_job_is_terminal_idempotent_and_never_invokes_engine(security):
    service = security.service()
    _, session = security.session()
    saved = accepted(security, service, session)
    request_id = saved["request"]["id"]
    first, status = service.cancel(session, request_id)
    again, repeat_status = service.cancel(session, request_id)
    assert status == repeat_status == 200
    assert first == again and first["request"]["state"] == "cancelled"
    assert not service.tick() and security.engine.calls == []


def test_expired_lease_cannot_refund_a_still_running_physical_slot(security):
    service, sweeper = security.service(), security.service()
    security.engine.release.clear()
    _, session = security.session()
    saved = accepted(security, service, session)
    request_id = saved["request"]["id"]
    # The old engine deliberately does not heartbeat after it has entered. Its
    # eventual answer is a late result, not evidence the external call ran twice.
    original = security.engine.run

    def stale(payload, control):
        return original(payload, lambda stage=None: None)

    security.engine.run = stale
    with ThreadPoolExecutor(max_workers=policy.RUNNING_GLOBAL) as pool:
        worker = pool.submit(service.tick)
        other_workers = []
        try:
            security.engine.wait_active(1)
            with security.storage.transaction() as conn:
                conn.execute(
                    "UPDATE app.analysis_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",
                    (request_id,),
                )
            sweeper.dispatch.housekeeping()
            with security.storage.transaction() as conn:
                row = conn.execute(
                    "SELECT state,physical_until>clock_timestamp(),lease_token FROM app.analysis_jobs WHERE id=%s",
                    (request_id,),
                ).fetchone()
                assert row[0] == "interrupted" and row[1] and row[2] >= 2
                assert conn.execute(
                    "SELECT count(*) FROM app.analysis_jobs WHERE physical_until>clock_timestamp()"
                ).fetchone() == (1,)
            assert security.engine.active == 1
            for number in range(policy.RUNNING_GLOBAL - 1):
                other_service = security.service()
                _, other_session = security.session(f"Other-running-{number}")
                accepted(security, other_service, other_session)
                other_workers.append(pool.submit(other_service.tick))
            security.engine.wait_active(policy.RUNNING_GLOBAL)
            _, overflow_owner = security.session("Queued-overlap-attempt")
            accepted(security, sweeper, overflow_owner)
            assert not sweeper.tick()
            assert security.engine.maximum == policy.RUNNING_GLOBAL
        finally:
            security.engine.release.set()
        assert worker.result(timeout=3)
        assert all(other.result(timeout=3) for other in other_workers)
    with security.storage.transaction() as conn:
        assert conn.execute(
            "SELECT state,physical_until FROM app.analysis_jobs WHERE id=%s",
            (request_id,),
        ).fetchone() == ("interrupted", None)
        assert conn.execute(
            "SELECT count(*) FROM app.visual_results WHERE request_id=%s", (request_id,)
        ).fetchone() == (0,)
    assert len(security.engine.calls) == policy.RUNNING_GLOBAL
    assert policy.KILL_GRACE_SECONDS > 0
