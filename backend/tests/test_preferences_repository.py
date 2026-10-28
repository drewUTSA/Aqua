"""Concurrency, compatibility and dependency-to-save authority races."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from threading import Barrier
import pytest
from psycopg.types.json import Jsonb
import main
from preferences.schema import DEFAULTS
from storage.pool import Storage

PATH = "/api/v1/me/preferences"


def snapshot(revision=1, **values):
    return {
        "schemaVersion": 1,
        "expectedRevision": revision,
        "values": {**deepcopy(DEFAULTS), **values},
    }


@pytest.fixture
def parallel_storage(world, monkeypatch):
    # A second real database lease exercises concurrent HTTP work rather than
    # relying on the ordinary fixture's one-slot pool to serialize everything.
    storage = Storage(replace(world.storage.settings, max_connections=2, max_waiting=4))
    monkeypatch.setattr(main.app.state, "storage", storage)
    try:
        yield storage
    finally:
        storage.close()


def test_two_devices_same_revision_have_one_winner(world, parallel_storage):
    a, owner = world.client("A")
    other_device, same_owner = world.client("A")
    assert owner == same_owner
    assert (
        a.get(PATH).json()["revision"] == other_device.get(PATH).json()["revision"] == 1
    )
    barrier = Barrier(2)

    def write(client, accent):
        barrier.wait(timeout=2)
        return accent, client.put(PATH, json=snapshot(accent=accent))

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(write, a, "sage")
        second = pool.submit(write, other_device, "amber")
        results = [first.result(timeout=5), second.result(timeout=5)]
    assert sorted(response.status_code for _, response in results) == [200, 409]
    winner = next(accent for accent, response in results if response.status_code == 200)
    authoritative = a.get(PATH).json()
    assert (
        authoritative["revision"] == 2 and authoritative["values"]["accent"] == winner
    )
    assert world.calls == []


def test_two_accounts_save_concurrently_with_separate_admission_and_values(
    world, parallel_storage
):
    a, owner = world.client("A", grant=False)
    b, other = world.client("B", grant=False)
    barrier = Barrier(2)

    def write(client, accent):
        barrier.wait(timeout=2)
        return client.put(PATH, json=snapshot(accent=accent))

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(write, a, "sage")
        second = pool.submit(write, b, "amber")
        assert first.result(timeout=5).status_code == 200
        assert second.result(timeout=5).status_code == 200
    with world.storage.transaction() as conn:
        for principal, accent in [(owner, "sage"), (other, "amber")]:
            assert conn.execute(
                "SELECT revision,values->>'accent' FROM app.user_preferences WHERE user_id=%s",
                (principal,),
            ).fetchone() == (2, accent)
            assert conn.execute(
                "SELECT hits FROM app.workspace_admission WHERE user_id=%s",
                (principal,),
            ).fetchone() == (1,)
    assert world.calls == []


def test_separate_cookies_share_budget_and_conflicts_do_not_refund_admission(world):
    a, owner = world.client("A")
    another, _ = world.client("A")
    b, other = world.client("B")
    assert a.put(PATH, json=snapshot(accent="sage")).status_code == 200
    assert another.put(PATH, json=snapshot(accent="amber")).status_code == 409
    with world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT hits FROM app.workspace_admission WHERE user_id=%s", (owner,)
        ).fetchone() == (2,)
        conn.execute(
            "UPDATE app.workspace_admission SET hits=60 WHERE user_id=%s", (owner,)
        )
    assert another.get(PATH).status_code == 429
    assert b.put(PATH, json=snapshot(accent="slate")).status_code == 200
    with world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT hits FROM app.workspace_admission WHERE user_id=%s", (owner,)
        ).fetchone() == (60,)
        assert conn.execute(
            "SELECT hits FROM app.workspace_admission WHERE user_id=%s", (other,)
        ).fetchone() == (1,)
    assert world.calls == []


def test_newer_schema_refuses_read_and_save_without_dropping_values(world):
    a, owner = world.client()
    held = {"future_preference": {"preserve_me": True}}
    with world.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.user_preferences SET schema_version=2,revision=17,values=%s WHERE user_id=%s",
            (Jsonb(held), owner),
        )
    for response in [a.get(PATH), a.put(PATH, json=snapshot(17, accent="sage"))]:
        assert (
            response.status_code == 409
            and response.json()["error"]["code"] == "unsupported_schema"
        )
        assert "preserve_me" not in response.text
    with world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT schema_version,revision,values FROM app.user_preferences WHERE user_id=%s",
            (owner,),
        ).fetchone() == (2, 17, held)
    assert world.calls == []


@pytest.mark.parametrize(
    "values", [{"unexpected_key": True}, {"accent": "unsafe"}, {"recents_count": True}]
)
def test_corrupt_current_schema_is_not_silently_overwritten(world, values):
    a, owner = world.client()
    with world.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.user_preferences SET values=%s WHERE user_id=%s",
            (Jsonb(values), owner),
        )
    assert a.get(PATH).status_code == 503
    assert a.put(PATH, json=snapshot(accent="sage")).status_code == 503
    with world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT revision,values FROM app.user_preferences WHERE user_id=%s",
            (owner,),
        ).fetchone() == (1, values)


def test_missing_known_keys_fill_defaults_and_missing_record_starts_at_revision_one(
    world,
):
    a, owner = world.client()
    with world.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.user_preferences SET values='{}' WHERE user_id=%s", (owner,)
        )
    assert a.get(PATH).json()["values"] == DEFAULTS
    with world.storage.transaction() as conn:
        conn.execute("DELETE FROM app.user_preferences WHERE user_id=%s", (owner,))
    assert a.get(PATH).json()["revision"] == 1
    assert a.put(PATH, json=snapshot(accent="sage")).json()["revision"] == 2


def test_grant_revocation_does_not_remove_owned_preference_access(world):
    a, owner = world.client()
    with world.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.dataset_grants SET revoked_at=clock_timestamp() WHERE user_id=%s",
            (owner,),
        )
    assert a.get(PATH).status_code == 200
    assert a.put(PATH, json=snapshot(accent="sage")).status_code == 200
    assert a.post("/api/v1/chats", json=world.body()).status_code == 403
    assert world.calls == []


def test_revocation_between_admission_and_data_transaction_is_rechecked(
    world, monkeypatch
):
    import preferences.router as router

    a, owner = world.client()
    original = router.guard
    calls = 0

    def revoke_after_admission(conn, session, policy):
        nonlocal calls
        original(conn, session, policy)
        calls += 1
        if calls == 1:
            conn.execute(
                "UPDATE app.sessions SET revoked_at=clock_timestamp() WHERE user_id=%s",
                (owner,),
            )

    monkeypatch.setattr(router, "guard", revoke_after_admission)
    assert a.put(PATH, json=snapshot(accent="sage")).status_code == 401
    with world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT revision,values FROM app.user_preferences WHERE user_id=%s",
            (owner,),
        ).fetchone() == (1, {})
    assert world.calls == []
