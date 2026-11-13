"""Actual disposable SQL retains uncertain legacy work across both deletion scopes.

Independent acceptance uses the existing explicit SyntheticAuthority fixture;
candidate selection, row locks, counters and bounded purge use PostgreSQL itself.
No provider is called. The offline case owns a real contained fixture child.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
from threading import Event
from uuid import uuid4

import pytest

from analysis import lifecycle, policy, queue, records
from analysis.process import ProcessEngine, payload
from nl2sql.config import Settings
from test_deletion_lifecycle import deletion as deletion
from test_deletion_lifecycle import PATH, request, settle, status
from workspace_fixtures import GOOD

SCOPES = ("chat_history_v1", "account_v1")
MARKERS = ("expired", "future", "quarantine")


def _marker(name: str, instant: datetime) -> datetime | None:
    return {
        "expired": instant - timedelta(seconds=1),
        "future": instant + timedelta(hours=1),
        "quarantine": datetime(9999, 1, 1, tzinfo=timezone.utc),
        "null": None,
    }[name]


def _legacy(world, owner: str, marker: str, *, age: int = 2) -> dict:
    """Real insert/terminal accounting; age recorded metadata without waiting an hour."""
    session = world.sessions[owner]
    with world.storage.transaction() as conn:
        job = records.insert(
            conn,
            session,
            str(uuid4()),
            "Private legacy housekeeping canary",
            "ollama",
            [],
            bytes(32),
            request_id=None,
        )
        conn.execute(
            "UPDATE app.analysis_jobs SET state='running',stage='context',"
            "started_at=clock_timestamp(),lease_token=1,lease_owner=%s,"
            "lease_until=clock_timestamp()+interval '15 seconds',"
            "physical_until=deadline_at+interval '15 seconds' WHERE id=%s",
            (str(uuid4()), job["id"]),
        )
        job = records.get(conn, owner, str(job["id"]), lock=True)
        if marker == "null":
            job = lifecycle.complete(conn, job, session, GOOD.copy(), 200)
            assert job["physical_until"] is None and job["content_bytes"] > 0
        else:
            job = lifecycle.terminate(
                conn,
                job,
                "interrupted",
                quarantine=marker == "quarantine",
                remote_uncertain=marker != "quarantine",
            )
            assert job["physical_until"] is not None and job["content_bytes"] == 0
        instant = conn.execute("SELECT clock_timestamp()").fetchone()[0]
        created = instant - timedelta(hours=age)
        conn.execute(
            "UPDATE app.analysis_jobs SET created_at=%s,deadline_at=%s,"
            "finished_at=%s,physical_until=%s WHERE id=%s",
            (
                created,
                created + timedelta(seconds=120),
                created,
                _marker(marker, instant),
                job["id"],
            ),
        )
        return records.get(conn, owner, str(job["id"]))


def _row(storage, identifier: str):
    with storage.transaction() as conn:
        return conn.execute(
            "SELECT state,physical_until,content_bytes,response FROM app.analysis_jobs "
            "WHERE id=%s",
            (identifier,),
        ).fetchone()


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("marker", MARKERS)
def test_housekeeping_never_turns_uncertain_physical_work_into_completed_deletion(
    deletion, scope, marker
):
    secure, _, service, worker = deletion
    client, owner = secure.client(linked=True)
    job = _legacy(secure.world, owner, marker)
    body = request(secure, client, owner, scope)
    assert client.post(PATH, json=body).status_code == 202
    for _ in range(12):
        secure.world.analysis.dispatch.housekeeping()
        worker.once()
    retained = _row(service.storage, str(job["id"]))
    assert retained is not None
    assert retained[:3] == (
        "interrupted",
        job["physical_until"],
        0,
    )
    receipt = status(client, body)
    assert receipt.status_code == 200
    assert receipt.json()["job"]["accepted"] is True
    assert receipt.json()["job"]["cleanup_complete"] is False
    # No engine/child was started by this metadata seed. Explicitly acknowledge
    # that synthetic supervisor's known exit, rather than a cleanup clock.
    with service.storage.transaction() as conn:
        current = records.get(conn, owner, str(job["id"]), lock=True)
        lifecycle.terminate(conn, current, "interrupted", reaped=True)
    settle(worker)
    assert status(client, body).json()["job"]["cleanup_complete"] is True
    assert _row(service.storage, str(job["id"])) is None
    assert secure.world.calls == []


@pytest.mark.parametrize("scope", SCOPES)
def test_confirmed_null_legacy_work_can_be_cleaned_and_deletion_completes(
    deletion, scope
):
    secure, _, service, worker = deletion
    client, owner = secure.client(linked=True)
    job = _legacy(secure.world, owner, "null")
    body = request(secure, client, owner, scope)
    assert client.post(PATH, json=body).status_code == 202
    secure.world.analysis.dispatch.housekeeping()
    assert _row(service.storage, str(job["id"])) is None
    settle(worker)
    assert status(client, body).json()["job"]["cleanup_complete"] is True


@pytest.mark.parametrize("marker", MARKERS)
def test_locked_recheck_preserves_candidate_that_gained_a_physical_claim(
    world, app_database, monkeypatch, marker
):
    _, owner = world.client()
    job = _legacy(world, owner, "null")
    selected, continue_cleanup = Event(), Event()
    actual_rows = queue.rows

    def selected_rows(conn, sql, *args):
        result = actual_rows(conn, sql, *args)
        if sql.startswith("SELECT id,user_id FROM app.analysis_jobs WHERE"):
            assert [str(row["id"]) for row in result] == [str(job["id"])]
            selected.set()
            assert continue_cleanup.wait(3), "candidate barrier expired"
        return result

    monkeypatch.setattr(queue, "rows", selected_rows)
    before = _row(world.storage, str(job["id"]))
    with ThreadPoolExecutor(max_workers=1) as threads:
        cleanup = threads.submit(world.analysis.dispatch.housekeeping)
        try:
            assert selected.wait(3), "real SQL did not select the NULL candidate"
            # This is a separate real PostgreSQL session/commit, after SELECT
            # but before Queue reacquires the user and job FOR UPDATE locks.
            app_database.execute("SET ROLE aqua_app_owner")
            instant = app_database.execute("SELECT clock_timestamp()").fetchone()[0]
            physical = _marker(marker, instant)
            changed = app_database.execute(
                "UPDATE app.analysis_jobs SET physical_until=%s WHERE id=%s RETURNING id",
                (physical, job["id"]),
            ).fetchall()
            assert changed == [(job["id"],)]
        finally:
            app_database.execute("RESET ROLE")
            continue_cleanup.set()
        cleanup.result(timeout=3)
    after = _row(world.storage, str(job["id"]))
    assert after == (before[0], physical, before[2], before[3])


def test_twenty_one_uncertain_rows_do_not_starve_eligible_null_cleanup(world):
    _, owner = world.client()
    retained = [_legacy(world, owner, "future", age=3) for _ in range(21)]
    eligible = _legacy(world, owner, "null", age=2)
    with world.storage.transaction() as conn:
        before = conn.execute(
            "SELECT content_bytes FROM app.workspace_totals WHERE singleton"
        ).fetchone()[0]
    world.analysis.dispatch.housekeeping()
    assert _row(world.storage, str(eligible["id"])) is None
    assert all(_row(world.storage, str(row["id"])) is not None for row in retained)
    with world.storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.analysis_jobs").fetchone() == (
            21,
        )
        assert conn.execute(
            "SELECT content_bytes FROM app.workspace_totals WHERE singleton"
        ).fetchone() == (before - eligible["content_bytes"],)
    assert (
        policy.RUNNING_GLOBAL,
        policy.RUNNING_OWNER,
        policy.QUEUED_GLOBAL,
        policy.QUEUED_OWNER,
    ) == (2, 1, 8, 2)


@pytest.mark.parametrize("scope", SCOPES)
def test_cleanup_refunds_once_and_preserves_other_owner_content_and_accounting(
    deletion, scope
):
    secure, _, service, worker = deletion
    client, owner = secure.client(linked=True)
    _, foreign = secure.world.client("B")
    held = _legacy(secure.world, owner, "expired")
    eligible = _legacy(secure.world, owner, "null")
    untouched = _legacy(secure.world, foreign, "null", age=0)
    other_before = _row(service.storage, str(untouched["id"]))
    with service.storage.transaction() as conn:
        total = conn.execute(
            "SELECT content_bytes FROM app.workspace_totals WHERE singleton"
        ).fetchone()[0]
        foreign_usage = conn.execute(
            "SELECT content_bytes FROM app.workspace_usage WHERE user_id=%s",
            (foreign,),
        ).fetchone()
    body = request(secure, client, owner, scope)
    assert client.post(PATH, json=body).status_code == 202
    for _ in range(12):
        secure.world.analysis.dispatch.housekeeping()
        worker.once()
    assert status(client, body).json()["job"]["cleanup_complete"] is False
    assert _row(service.storage, str(eligible["id"])) is None
    assert _row(service.storage, str(held["id"])) is not None
    assert _row(service.storage, str(untouched["id"])) == other_before
    with service.storage.transaction() as conn:
        assert conn.execute(
            "SELECT content_bytes FROM app.workspace_totals WHERE singleton"
        ).fetchone() == (total - eligible["content_bytes"],)
        assert (
            conn.execute(
                "SELECT content_bytes FROM app.workspace_usage WHERE user_id=%s",
                (foreign,),
            ).fetchone()
            == foreign_usage
        )
        current = records.get(conn, owner, str(held["id"]), lock=True)
        lifecycle.terminate(conn, current, "interrupted", reaped=True)
    settle(worker)
    assert status(client, body).json()["job"]["cleanup_complete"] is True
    assert _row(service.storage, str(untouched["id"])) == other_before
    with service.storage.transaction() as conn:
        assert conn.execute(
            "SELECT content_bytes FROM app.workspace_totals WHERE singleton"
        ).fetchone() == (total - eligible["content_bytes"],)


def test_offline_restore_clears_uncertainty_only_after_owned_fixture_host_exit(
    world, app_database, monkeypatch
):
    import analysis.process as process_module

    _, owner = world.client()
    job = _legacy(world, owner, "quarantine")
    actual_spawn, observed, entered = subprocess.Popen, [], Event()

    def fixture_spawn(arguments, **options):
        index = arguments.index("-m")
        child = actual_spawn(
            [
                *arguments[:index],
                str(Path(__file__).with_name("analysis_process_child.py")),
                *arguments[index + 2 :],
            ],
            **options,
        )
        observed.append(child)
        return child

    def control(stage):
        if stage == "generating":
            entered.set()

    monkeypatch.setattr(process_module.subprocess, "Popen", fixture_spawn)
    engine = ProcessEngine()
    with ThreadPoolExecutor(max_workers=1) as threads:
        work = threads.submit(engine.run, payload(job, "hold", Settings(), 5), control)
        try:
            assert entered.wait(3), "owned contained fixture host did not start"
            assert len(observed) == 1 and observed[0].poll() is None
            world.analysis.dispatch.housekeeping()
            assert _row(world.storage, str(job["id"]))[1] == job["physical_until"]
            # The offline fence is deliberately not executed while this actual
            # owned child is alive. The SQL itself is not an exit detector.
        finally:
            engine.close()
        assert work.exception(timeout=3) is not None
    assert observed[0].poll() is not None and not engine.children
    fence = Path(__file__).resolve().parents[2] / "ops/appdb/restore_session_fence.sql"
    app_database.execute(fence.read_text(), prepare=False)
    assert _row(world.storage, str(job["id"]))[:3] == ("interrupted", None, 0)
    world.analysis.dispatch.housekeeping()
    assert _row(world.storage, str(job["id"])) is None
