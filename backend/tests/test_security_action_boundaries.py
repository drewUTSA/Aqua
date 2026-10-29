"""Direct API callers cannot replace current owner, CSRF, target or proof policy."""

import pytest
from fastapi.testclient import TestClient

import main
from auth.sessions import new_token, token_digest
from security_action_fixtures import NEW, PATH

ROUTES = [
    ("POST", "/reauth-challenges", {"operation": "password_change"}),
    (
        "POST",
        "/reauth/password",
        {
            "operation": "password_change",
            "challenge_id": "00000000-0000-4000-8000-000000000001",
            "challenge_token": "v2." + "a" * 43,
            "password": "Synthetic stable account password 27",
        },
    ),
    ("PUT", "/password", {"proof_token": "v2." + "a" * 43, "new_password": NEW}),
    ("POST", "/session-revocations", {"proof_token": "v2." + "a" * 43}),
    (
        "POST",
        "/sessions/00000000-0000-4000-8000-000000000001/revocations",
        {"proof_token": "v2." + "a" * 43},
    ),
]


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_anonymous_csrf_query_and_extra_owner_fields_fail_closed(
    account_security, method, path, body
):
    client, owner = account_security.client()
    anonymous = TestClient(
        main.app, base_url=account_security.world.settings.app_origin
    )
    assert anonymous.request(method, PATH + path, json=body).status_code == 401
    for headers in [{"Origin": "https://attacker.invalid"}, {"X-CSRF-Token": "wrong"}]:
        assert (
            client.request(method, PATH + path, json=body, headers=headers).status_code
            == 403
        )
    assert (
        client.request(method, PATH + path + "?owner_id=forged", json=body).status_code
        == 422
    )
    for key in [
        "owner_id",
        "user_id",
        "auth_epoch",
        "target_digest",
        "method",
        "verified",
        "role",
        "__proto__",
    ]:
        assert (
            client.request(
                method, PATH + path, json={**body, key: "forged"}
            ).status_code
            == 422
        )
    assert account_security.hasher.calls == [] and account_security.world.calls == []
    with account_security.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.account_action_proofs WHERE user_id=%s", (owner,)
        ).fetchone() == (0,)


@pytest.mark.parametrize("change", ["revoked", "epoch", "disabled", "expired"])
def test_stale_authenticated_sessions_cannot_start_sensitive_work(
    account_security, change
):
    client, owner = account_security.client()
    with account_security.world.storage.transaction() as conn:
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
    for method, path, body in ROUTES:
        assert client.request(method, PATH + path, json=body).status_code == 401
    assert account_security.hasher.calls == [] and account_security.world.calls == []


def test_foreign_session_target_never_creates_challenge_or_spends_a_hash(
    account_security,
):
    client, owner = account_security.client()
    other, _ = account_security.client("B")
    sid = other.get(PATH + "/sessions").json()["items"][0]["id"]
    assert (
        client.post(
            PATH + "/reauth-challenges",
            json={"operation": "session_revoke", "target_session_id": sid},
        ).status_code
        == 404
    )
    assert account_security.hasher.calls == []
    with account_security.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.auth_challenges WHERE user_id=%s AND account_operation IS NOT NULL",
            (owner,),
        ).fetchone() == (0,)


def test_sensitive_json_limits_duplicates_and_missing_proof_do_no_hash_work(
    account_security,
):
    client, _ = account_security.client()
    for data, status in [
        (
            b'{"operation":"password_change","operat\\u0069on":"sessions_revoke_all"}',
            422,
        ),
        (b"[" * 3000 + b"]" * 3000, 422),
        (b"x" * 16385, 413),
    ]:
        assert (
            client.post(
                PATH + "/reauth-challenges",
                content=data,
                headers={"Content-Type": "application/json"},
            ).status_code
            == status
        )
    assert (
        client.post(
            PATH + "/reauth-challenges",
            content="{}",
            headers={"Content-Type": "text/plain"},
        ).status_code
        == 415
    )
    assert client.put(PATH + "/password", json={"new_password": NEW}).status_code == 422
    assert account_security.hasher.calls == []


def test_bound_proof_cannot_be_retargeted_or_replayed_to_revoke_another_session(
    account_security,
):
    client, _ = account_security.client()
    other, _ = account_security.client()
    third, _ = account_security.client()
    sid = other.get(PATH + "/sessions").json()["items"][0]["id"]
    different = third.get(PATH + "/sessions").json()["items"][0]["id"]
    proof = account_security.proof(client, "session_revoke", sid)
    assert (
        client.post(
            PATH + "/sessions/" + different + "/revocations",
            json={"proof_token": proof},
        ).status_code
        == 403
    )
    assert (
        client.post(
            PATH + "/session-revocations", json={"proof_token": proof}
        ).status_code
        == 403
    )
    assert (
        client.post(
            PATH + "/sessions/" + sid + "/revocations", json={"proof_token": proof}
        ).status_code
        == 200
    )
    assert (
        client.post(
            PATH + "/sessions/" + sid + "/revocations", json={"proof_token": proof}
        ).status_code
        == 404
    )
    assert third.get(PATH).status_code == 200 and client.get(PATH).status_code == 200
    with account_security.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT consumed_at IS NOT NULL FROM app.account_action_proofs WHERE secret_digest=%s",
            (token_digest(proof),),
        ).fetchone() == (True,)


def test_tokens_are_not_ordinary_password_reset_or_registration_proof(account_security):
    client, owner = account_security.client()
    proof = new_token()
    assert (
        client.put(
            PATH + "/password", json={"proof_token": proof, "new_password": NEW}
        ).status_code
        == 403
    )
    assert (
        client.post(
            PATH + "/reauth-challenges", json={"operation": "google_link"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            PATH + "/reauth-challenges", json={"operation": "password_add"}
        ).status_code
        == 422
    )
    with account_security.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT auth_epoch FROM app.users WHERE id=%s", (owner,)
        ).fetchone() == (0,)


def test_cookie_switch_cannot_pair_an_old_owner_csrf_with_a_different_account(
    account_security, monkeypatch
):
    from unittest.mock import Mock
    from auth.sessions import session_cookie_name

    old, _ = account_security.client()
    switched, _ = account_security.client("B")
    name = session_cookie_name(account_security.world.settings)
    cookie = switched.cookies.get(name)
    forbidden_sql = Mock(side_effect=AssertionError("cross-owner CSRF reached SQL"))
    with monkeypatch.context() as isolated:
        isolated.setattr(account_security.world.storage, "transaction", forbidden_sql)
        for method, path, body in ROUTES:
            response = old.request(
                method,
                PATH + path,
                json=body,
                headers={
                    "Cookie": name + "=" + cookie,
                    "X-CSRF-Token": old.headers["X-CSRF-Token"],
                },
            )
            assert response.status_code == 403
    forbidden_sql.assert_not_called()
    assert account_security.hasher.calls == [] and account_security.world.calls == []
