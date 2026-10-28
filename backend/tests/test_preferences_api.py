"""Real-session account-only settings with disposable PostgreSQL and fake models."""

from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
import main
from preferences.schema import DEFAULTS

PATH = "/api/v1/me/preferences"


def snapshot(revision=1, **values):
    return {
        "schemaVersion": 1,
        "expectedRevision": revision,
        "values": {**deepcopy(DEFAULTS), **values},
    }


def stored(world, owner):
    with world.storage.transaction() as conn:
        return conn.execute(
            "SELECT schema_version,revision,values FROM app.user_preferences WHERE user_id=%s",
            (owner,),
        ).fetchone()


def test_pending_data_account_can_save_reload_and_other_owner_is_unchanged(world):
    a, owner = world.client("A", grant=False)
    b, other = world.client("B", grant=False)
    initial = a.get(PATH)
    assert initial.status_code == 200 and initial.json()["values"] == DEFAULTS
    saved = a.put(
        PATH, json=snapshot(accent="sage", sidebar_sections=["prompts", "recents"])
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 2 and saved.json()["values"]["accent"] == "sage"
    restored, same_owner = world.client("A", grant=False)
    assert same_owner == owner and restored.get(PATH).json() == saved.json()
    assert b.get(PATH).json()["values"] == DEFAULTS
    assert stored(world, other)[1:] == (1, {})
    assert saved.headers["cache-control"] == "no-store"
    assert "Cookie" in saved.headers["vary"]
    assert world.calls == []


@pytest.mark.parametrize("change", ["revoked", "epoch", "disabled", "expired"])
def test_session_loss_prevents_read_and_write(world, change):
    a, owner = world.client()
    before = stored(world, owner)
    with world.storage.transaction() as conn:
        if change == "revoked":
            conn.execute(
                "UPDATE app.sessions SET revoked_at=clock_timestamp() WHERE user_id=%s",
                (owner,),
            )
        elif change == "epoch":
            conn.execute(
                "UPDATE app.users SET auth_epoch=auth_epoch+1 WHERE id=%s", (owner,)
            )
        elif change == "disabled":
            conn.execute("UPDATE app.users SET status='disabled' WHERE id=%s", (owner,))
        else:
            conn.execute(
                "UPDATE app.sessions SET created_at=now()-interval '2 hours',idle_expires_at=now()-interval '1 hour',absolute_expires_at=now()-interval '30 minutes' WHERE user_id=%s",
                (owner,),
            )
    assert (
        a.get(PATH).status_code
        == a.put(PATH, json=snapshot(accent="amber")).status_code
        == 401
    )
    assert stored(world, owner) == before and world.calls == []


def test_missing_session_and_csrf_rejections_do_no_preference_work(world):
    a, owner = world.client()
    before = stored(world, owner)
    anonymous = TestClient(main.app, base_url=world.settings.app_origin)
    assert anonymous.get(PATH).status_code == 401
    assert anonymous.put(PATH, json=snapshot()).status_code == 401
    for headers in [
        {"Origin": "https://evil.invalid"},
        {"X-CSRF-Token": "bad"},
        {"X-CSRF-Token": ""},
    ]:
        result = a.put(PATH, json=snapshot(accent="sage"), headers=headers)
        assert result.status_code == 403 and "evil.invalid" not in result.text
    assert stored(world, owner) == before and world.calls == []


@pytest.mark.parametrize(
    "field",
    [
        "owner_id",
        "user_id",
        "role",
        "dataset_grants",
        "consent",
        "__proto__",
        "constructor",
    ],
)
def test_forged_owner_and_mass_assignment_are_atomic(world, field):
    a, owner = world.client()
    b, other = world.client("B")
    before = stored(world, owner), stored(world, other)
    body = snapshot(accent="sage")
    body["values"][field] = str(other)
    assert a.put(PATH, json=body).status_code == 422
    assert a.put(PATH, json={**snapshot(), field: str(other)}).status_code == 422
    assert a.get(PATH, params={field: str(other)}).status_code == 422
    assert a.put(PATH + "?user_id=" + str(other), json=snapshot()).status_code == 422
    assert a.get(PATH + "/" + str(other)).status_code == 404
    assert (stored(world, owner), stored(world, other)) == before and world.calls == []
    assert b.get(PATH).json()["values"] == DEFAULTS


def test_body_byte_limit_media_type_duplicate_keys_and_deep_json_are_rejected(world):
    a, owner = world.client()
    before = stored(world, owner)
    for body, status in [
        (b"x" * 65537, 413),
        (b'{"schemaVersion":1,"schemaVersion":2}', 422),
        (b"[" * 3000 + b"]" * 3000, 422),
    ]:
        response = a.put(
            PATH, content=body, headers={"Content-Type": "application/json"}
        )
        assert response.status_code == status, response.text
    assert (
        a.put(PATH, content="bad", headers={"Content-Type": "text/plain"}).status_code
        == 415
    )
    assert stored(world, owner) == before and world.calls == []


def test_revision_conflicts_lost_response_and_budget_recovery(world):
    a, owner = world.client()
    body = snapshot(accent="sage")
    assert a.put(PATH, json=body).status_code == 200
    assert a.put(PATH, json=body).status_code == 409
    assert a.get(PATH).json()["revision"] == 2
    with world.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.workspace_admission SET hits=60,expires_at=clock_timestamp()+interval '1 minute' WHERE user_id=%s",
            (owner,),
        )
    denied = a.put(PATH, json=snapshot(2, accent="amber"))
    assert denied.status_code == 429 and denied.headers["retry-after"] == "60"
    assert stored(world, owner)[1] == 2
    with world.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.workspace_admission SET expires_at=clock_timestamp()-interval '1 second' WHERE user_id=%s",
            (owner,),
        )
    assert a.put(PATH, json=snapshot(2, accent="amber")).status_code == 200
    assert stored(world, owner)[1:] == (3, snapshot(accent="amber")["values"])
    assert world.calls == []
