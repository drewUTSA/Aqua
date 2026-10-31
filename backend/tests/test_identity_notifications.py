"""Notification consent is independent CAS, never optional email/permission."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from fastapi import Request
import main
from auth.security import get_store
from auth.sessions import session_cookie_name
from auth.store import IdentityStore
from storage.pool import Storage
from security_action_fixtures import PATH


def test_notifications_default_off_and_explicit_save_cannot_change_preferences(
    identity_security,
):
    secure = identity_security
    client, owner = secure.client(linked=False)
    foreign, _ = secure.client("B", linked=False)
    with secure.world.storage.transaction() as conn:
        before = conn.execute(
            "SELECT revision,values FROM app.user_preferences WHERE user_id=%s",
            (owner,),
        ).fetchone()
        activity = conn.execute(
            "SELECT last_activity_at,idle_expires_at FROM app.sessions WHERE user_id=%s",
            (owner,),
        ).fetchall()
    response = client.get(PATH + "/notification-settings")
    body = response.json()
    assert (
        response.status_code == 200
        and body["user_id"] == owner
        and body["revision"] == 1
    )
    assert body["values"] == {"in_app_success": False, "preview": "generic"}
    assert body["capabilities"] == {
        "in_app": True,
        "browser": False,
        "email": False,
        "sound": False,
        "quiet_hours": False,
    }
    with secure.world.storage.transaction() as conn:
        assert (
            conn.execute(
                "SELECT last_activity_at,idle_expires_at FROM app.sessions WHERE user_id=%s",
                (owner,),
            ).fetchall()
            == activity
        )
    result = client.put(
        PATH + "/notification-settings",
        json={"expectedRevision": 1, "in_app_success": True, "preview": "hidden"},
    )
    assert result.status_code == 200 and result.json()["revision"] == 2
    assert (
        client.put(
            PATH + "/notification-settings",
            json={"expectedRevision": 1, "in_app_success": False, "preview": "generic"},
        ).status_code
        == 409
    )
    assert (
        foreign.get(PATH + "/notification-settings").json()["values"]["in_app_success"]
        is False
    )
    with secure.world.storage.transaction() as conn:
        assert (
            conn.execute(
                "SELECT revision,values FROM app.user_preferences WHERE user_id=%s",
                (owner,),
            ).fetchone()
            == before
        )
        assert conn.execute(
            "SELECT profile_revision FROM app.users WHERE id=%s", (owner,)
        ).fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM app.account_mail").fetchone() == (0,)
    assert secure.provider_calls == [] and secure.hasher.calls == []


def test_notification_cas_across_pools_has_one_winner_and_spends_both_admissions(
    identity_security, monkeypatch
):
    secure = identity_security
    left, owner = secure.client()
    right, _ = secure.client()
    _, foreign_owner = secure.client("B")
    assert left.get(PATH + "/notification-settings").status_code == 200
    with secure.world.storage.transaction() as conn:
        before = conn.execute(
            "SELECT hits FROM app.workspace_admission WHERE user_id=%s", (owner,)
        ).fetchone()[0]
    pools = [
        Storage(replace(secure.world.storage.settings, max_waiting=2, wait_seconds=2))
        for _ in range(2)
    ]
    cookie = session_cookie_name(secure.world.settings)
    stores = {
        client.cookies.get(cookie): IdentityStore(pool, secure.world.policy)
        for client, pool in zip([left, right], pools, strict=True)
    }

    def store(request: Request):
        return stores[request.cookies.get(cookie)]

    monkeypatch.setitem(main.app.dependency_overrides, get_store, store)
    barrier = Barrier(2)

    def save(client):
        barrier.wait(timeout=4)
        return client.put(
            PATH + "/notification-settings",
            json={"expectedRevision": 1, "in_app_success": True, "preview": "hidden"},
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(save, [left, right]))
        assert sorted(result.status_code for result in results) == [200, 409]
        with secure.world.storage.transaction() as conn:
            assert conn.execute(
                "SELECT revision,in_app_success,preview FROM app.user_notification_settings WHERE user_id=%s",
                (owner,),
            ).fetchone() == (2, True, "hidden")
            assert conn.execute(
                "SELECT hits FROM app.workspace_admission WHERE user_id=%s", (owner,)
            ).fetchone() == (before + 2,)
            assert conn.execute(
                "SELECT count(*) FROM app.user_notification_settings WHERE user_id=%s",
                (foreign_owner,),
            ).fetchone() == (0,)
    finally:
        for pool in pools:
            pool.close()


def test_preferences_cannot_import_notification_consent(identity_security):
    secure = identity_security
    client, _ = secure.client()
    prefs = client.get(PATH + "/preferences").json()
    response = client.put(
        PATH + "/preferences",
        json={
            "schemaVersion": 1,
            "expectedRevision": prefs["revision"],
            "values": {**prefs["values"], "in_app_success": True},
        },
    )
    assert response.status_code == 422
    assert client.get(PATH + "/notification-settings").json()["values"] == {
        "in_app_success": False,
        "preview": "generic",
    }
