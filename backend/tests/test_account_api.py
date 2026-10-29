"""P10a against disposable private roles and genuine cookie/CSRF sessions."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

import main
from account.policy import CAPABILITIES
from auth.security import get_store
from auth.sessions import session_cookie_name
from auth.store import IdentityStore
from storage.pool import Storage

PATH = "/api/v1/me"
READS = (PATH, PATH + "/methods", PATH + "/sessions")


def state(world, owner):
    with world.storage.transaction() as conn:
        return conn.execute(
            "SELECT display_name,picture,profile_revision,auth_epoch FROM app.users WHERE id=%s",
            (owner,),
        ).fetchone()


def test_account_without_data_grant_has_private_bounded_reads_without_idle_refresh(
    world,
):
    a, owner = world.client(grant=False)
    b, other = world.client("B", grant=False)
    with world.storage.transaction() as conn:
        before = conn.execute(
            "SELECT last_activity_at,idle_expires_at,authenticated_at FROM app.sessions WHERE user_id=%s",
            (owner,),
        ).fetchall()
    profile = a.get(PATH)
    assert profile.status_code == 200 and profile.json()["capabilities"] == CAPABILITIES
    assert (
        profile.json()["user"]["id"] == owner
        and profile.json()["email_verified"] is True
    )
    methods = a.get(PATH + "/methods").json()
    assert methods["google"]["linked"] and not methods["password"]["linked"]
    listed = a.get(PATH + "/sessions").json()
    assert len(listed["items"]) == 1 and listed["items"][0]["current"] is True
    assert listed["items"][0]["device_label"] == "Unknown device"
    assert b.get(PATH).json()["user"]["id"] == other
    for response in [profile, a.get(PATH + "/methods"), a.get(PATH + "/sessions")]:
        assert response.headers["cache-control"] == "no-store"
        assert "cookie" in response.headers["vary"].lower()
        for forbidden in [
            "token_digest",
            "csrf_digest",
            "encoded_hash",
            "observed_email",
            "subject",
            "fixture-peer",
        ]:
            assert forbidden not in response.text
    with world.storage.transaction() as conn:
        assert (
            conn.execute(
                "SELECT last_activity_at,idle_expires_at,authenticated_at FROM app.sessions WHERE user_id=%s",
                (owner,),
            ).fetchall()
            == before
        )
    assert world.calls == []


def test_display_name_cas_preserves_canonical_authority_on_returning_google_login(
    world,
):
    a, owner = world.client(grant=False)
    second, _ = world.client(grant=False)
    b, other = world.client("B", grant=False)
    before_b = state(world, other)
    result = a.patch(
        PATH, json={"expectedRevision": 1, "display_name": "  Custom name  "}
    )
    assert result.status_code == 200 and result.json()["revision"] == 2
    assert result.json()["user"]["name"] == "Custom name"
    assert (
        second.patch(
            PATH, json={"expectedRevision": 1, "display_name": "Stale"}
        ).status_code
        == 409
    )
    # A later signed provider observation may now match B's app primary. It
    # neither claims B's mailbox nor reverts A's app-managed profile/primary.
    from auth.sessions import token_digest, new_token

    world.store.login(
        {
            "sub": "workspace-A",
            "email": "b@gmail.com",
            "email_verified": True,
            "name": "Provider overwrite",
            "picture": "",
        },
        token_digest(new_token()),
        token_digest(new_token()),
        "fixture",
        world.settings,
    )
    restored = a.get(PATH).json()
    assert restored["user"]["name"] == "Custom name"
    assert restored["user"]["email"] == "a@gmail.com" and restored["revision"] == 2
    assert (
        state(world, other) == before_b
        and b.get(PATH).json()["user"]["email"] == "b@gmail.com"
    )


@pytest.mark.parametrize("path", READS)
def test_account_reads_deny_anonymous_and_owner_query_selectors(world, path):
    a, _ = world.client(grant=False)
    anonymous = TestClient(main.app, base_url=world.settings.app_origin)
    assert anonymous.get(path).status_code == 401
    assert a.get(path + "?owner_id=forged").status_code == 422
    assert a.get(path + "/00000000-0000-4000-8000-000000000001").status_code == 404


@pytest.mark.parametrize("change", ["revoked", "epoch", "disabled", "expired"])
def test_account_current_authority_is_rechecked(world, change):
    a, owner = world.client(grant=False)
    with world.storage.transaction() as conn:
        if change == "revoked":
            conn.execute(
                "UPDATE app.sessions SET revoked_at=now() WHERE user_id=%s", (owner,)
            )
        elif change == "epoch":
            conn.execute(
                "UPDATE app.users SET auth_epoch=auth_epoch+1 WHERE id=%s", (owner,)
            )
        elif change == "disabled":
            conn.execute("UPDATE app.users SET status='disabled' WHERE id=%s", (owner,))
        else:
            conn.execute(
                "UPDATE app.sessions SET created_at=now()-interval '2 hours',idle_expires_at=now()-interval '1 hour' WHERE user_id=%s",
                (owner,),
            )
    assert all(a.get(path).status_code == 401 for path in READS)
    assert (
        a.patch(
            PATH, json={"expectedRevision": 1, "display_name": "denied"}
        ).status_code
        == 401
    )
    assert state(world, owner)[0] == "A"


def test_profile_csrf_mass_assignment_duplicate_keys_and_limits_are_atomic(world):
    a, owner = world.client(grant=False)
    before = state(world, owner)
    body = {"expectedRevision": 1, "display_name": "New"}
    for headers in [{"Origin": "https://evil.invalid"}, {"X-CSRF-Token": "bad"}]:
        assert a.patch(PATH, json=body, headers=headers).status_code == 403
    for key in [
        "user_id",
        "email",
        "picture",
        "proof",
        "auth_epoch",
        "role",
        "__proto__",
    ]:
        assert a.patch(PATH, json={**body, key: "forged"}).status_code == 422
    for raw, status in [
        (b'{"expectedRevision":1,"display_name":"X","display_nam\\u0065":"Y"}', 422),
        (b"[" * 3000 + b"]" * 3000, 422),
        (b"x" * 16385, 413),
    ]:
        assert (
            a.patch(
                PATH, content=raw, headers={"Content-Type": "application/json"}
            ).status_code
            == status
        )
    assert (
        a.patch(PATH, content="{}", headers={"Content-Type": "text/plain"}).status_code
        == 415
    )
    assert a.patch(PATH + "?user_id=forged", json=body).status_code == 422
    assert state(world, owner) == before and world.calls == []


def test_account_budget_is_shared_with_preferences_and_failed_cas(world):
    a, owner = world.client(grant=False)
    assert a.get(PATH).status_code == 200
    with world.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.workspace_admission SET hits=60,expires_at=now()+interval '1 minute' WHERE user_id=%s",
            (owner,),
        )
    for path in (*READS, PATH + "/preferences"):
        response = a.get(path)
        assert response.status_code == 429 and response.headers["retry-after"] == "60"
    assert (
        a.patch(
            PATH, json={"expectedRevision": 9, "display_name": "denied"}
        ).status_code
        == 429
    )
    assert state(world, owner)[0] == "A"


def test_future_security_actions_are_unmounted(world):
    a, _ = world.client(grant=False)
    for path in [
        "/email-change-requests",
        "/password-add",
        "/reauth/google",
        "/identities/google",
        "/notifications",
    ]:
        assert a.post(PATH + path, json={}).status_code == 404


def test_concurrent_profile_cas_across_pools_has_one_winner_and_spends_both_admissions(
    world, monkeypatch
):
    left, owner = world.client(grant=False)
    right, _ = world.client(grant=False)
    _, foreign = world.client("B", grant=False)
    foreign_before = state(world, foreign)
    with world.storage.transaction() as conn:
        row = conn.execute(
            "SELECT hits FROM app.workspace_admission WHERE user_id=%s", (owner,)
        ).fetchone()
        before_hits = row[0] if row else 0
    settings = replace(world.storage.settings, max_waiting=2, wait_seconds=2)
    pools = [Storage(settings), Storage(settings)]
    cookie = session_cookie_name(world.settings)
    stores = {
        client.cookies.get(cookie): IdentityStore(pool, world.policy)
        for client, pool in zip([left, right], pools, strict=True)
    }

    def isolated_store(request: Request):
        return stores[request.cookies.get(cookie)]

    monkeypatch.setitem(main.app.dependency_overrides, get_store, isolated_store)
    ready = Barrier(2)

    def save(pair):
        client, name = pair
        ready.wait(timeout=3)
        return client.patch(PATH, json={"expectedRevision": 1, "display_name": name})

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(
                workers.map(
                    save,
                    [(left, "First proposed name"), (right, "Second proposed name")],
                )
            )
        assert sorted(result.status_code for result in results) == [200, 409]
        winner = next(result.json() for result in results if result.status_code == 200)
        assert winner["revision"] == 2
        stored = state(world, owner)
        assert (stored[0], stored[2]) == (winner["user"]["name"], 2)
        assert state(world, foreign) == foreign_before
        with world.storage.transaction() as conn:
            assert conn.execute(
                "SELECT hits FROM app.workspace_admission WHERE user_id=%s", (owner,)
            ).fetchone() == (before_hits + 2,)
        assert world.calls == []
    finally:
        for pool in pools:
            pool.close()
