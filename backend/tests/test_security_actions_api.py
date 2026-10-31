"""Sensitive routes require genuine current sessions, CSRF and exact one-use proof."""

from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import main
from account.security_http import binding_cookie
from auth.password_hash import PasswordHasher
from auth.mailoutbox import MailJob, open_job
from auth.sessions import bound_value, new_token, session_cookie_name, token_digest
from auth.config import AuthDenied
from security_action_fixtures import NEW, OLD, PATH


def state(account_security, owner):
    with account_security.world.storage.transaction() as conn:
        return conn.execute(
            "SELECT u.auth_epoch,p.encoded_hash,p.changed_at FROM app.users u JOIN app.password_credentials p ON p.user_id=u.id WHERE u.id=%s",
            (owner,),
        ).fetchone()


def test_issued_proof_is_digest_only_short_lived_and_not_session_freshness(
    account_security,
):
    client, owner = account_security.client()
    before = state(account_security, owner)
    challenge_response = client.post(
        PATH + "/reauth-challenges", json={"operation": "password_change"}
    )
    assert challenge_response.status_code == 200
    challenge = challenge_response.json()
    binding_header = challenge_response.headers["set-cookie"]
    assert all(
        part in binding_header
        for part in ("Path=/", "HttpOnly", "SameSite=lax", "Secure", "Max-Age=300")
    )
    cookie = client.cookies.get(binding_cookie(account_security.world.settings))
    assert cookie and challenge["methods"] == ["password"]
    response = client.post(
        PATH + "/reauth/password",
        json={
            "operation": "password_change",
            "challenge_id": challenge["challenge_id"],
            "challenge_token": challenge["challenge_token"],
            "password": OLD,
        },
    )
    assert (
        response.status_code == 200 and response.headers["cache-control"] == "no-store"
    )
    proof = response.json()
    assert set(proof) == {"schemaVersion", "proof_token", "expires_at"}
    with account_security.world.storage.transaction() as conn:
        row = conn.execute(
            "SELECT c.consumed_at,p.secret_digest,p.method,p.password_changed_at,p.auth_epoch,p.expires_at<=c.expires_at,p.expires_at-p.created_at<=interval '300 seconds',s.authenticated_at=s.created_at FROM app.account_action_proofs p JOIN app.auth_challenges c ON c.id=p.challenge_id JOIN app.sessions s ON s.id=p.session_id WHERE p.user_id=%s",
            (owner,),
        ).fetchone()
    assert row[0] is not None and bytes(row[1]) == token_digest(proof["proof_token"])
    assert row[2:5] == ("password", before[2], 0) and row[5:] == (True, True, True)
    assert datetime.fromisoformat(proof["expires_at"]) <= datetime.fromisoformat(
        challenge["expires_at"]
    )
    assert (
        account_security.hasher.calls == ["verify"]
        and account_security.world.calls == []
    )


def test_password_change_commits_notice_and_revokes_all_owned_cookies_only(
    account_security,
):
    client, owner = account_security.client()
    other, _ = account_security.client()
    foreign, foreign_owner = account_security.client("B")
    foreign_before = state(account_security, foreign_owner)
    copied = TestClient(main.app, base_url=account_security.world.settings.app_origin)
    copied.cookies.update(client.cookies)
    proof = account_security.proof(client)
    response = client.put(
        PATH + "/password", json={"proof_token": proof, "new_password": NEW}
    )
    assert response.status_code == 200 and response.json() == {
        "schemaVersion": 1,
        "password_changed": True,
        "current_session_revoked": True,
    }
    # world.client installs a hostless test cookie. Check the actual deletion
    # header rather than assuming httpx removes that synthetic cookie domain.
    removed = [
        value
        for value in response.headers.get_list("set-cookie")
        if value.startswith(session_cookie_name(account_security.world.settings) + "=")
    ]
    assert len(removed) == 1 and "Max-Age=0" in removed[0]
    assert all(value.get(PATH).status_code == 401 for value in (client, copied, other))
    assert (
        foreign.get(PATH).status_code == 200
        and state(account_security, foreign_owner) == foreign_before
    )
    assert state(account_security, owner)[0:2] == (
        1,
        account_security.hasher.encoded(NEW),
    )
    with account_security.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.account_mail WHERE purpose='password_changed' AND state='pending'"
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT consumed_at IS NOT NULL FROM app.account_action_proofs WHERE secret_digest=%s",
            (token_digest(proof),),
        ).fetchone() == (True,)
        row = conn.execute(
            "SELECT id,purpose,recipient_digest,ciphertext,expires_at FROM app.account_mail WHERE purpose='password_changed'"
        ).fetchone()
    notice = open_job(MailJob(*row, uuid4(), 0), account_security.passwords.mail_policy)
    assert notice["to"] == "a@gmail.com"
    assert all(secret not in str(notice) for secret in (OLD, NEW, proof))
    raw = new_token()
    csrf = bound_value(account_security.world.settings, raw, "session-csrf")
    with pytest.raises(AuthDenied):
        account_security.passwords.login(
            "a@gmail.com",
            OLD,
            token_digest(raw),
            token_digest(csrf),
            "fixture",
            account_security.world.settings,
        )
    current = account_security.passwords.login(
        "a@gmail.com",
        NEW,
        token_digest(raw),
        token_digest(csrf),
        "fixture",
        account_security.world.settings,
    )
    assert current.user["id"] == owner and not current.can_query


def test_real_argon2_password_verification_and_change_reuse_reviewed_hasher(
    account_security,
):
    client, owner = account_security.client()
    hasher = PasswordHasher()
    encoded = hasher.hash(OLD)
    with account_security.world.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.password_credentials SET encoded_hash=%s WHERE user_id=%s",
            (encoded, owner),
        )
    account_security.passwords.hasher = hasher
    proof = account_security.proof(client)
    assert (
        client.put(
            PATH + "/password", json={"proof_token": proof, "new_password": NEW}
        ).status_code
        == 200
    )
    assert hasher.verify(NEW, state(account_security, owner)[1]) and not hasher.verify(
        OLD, state(account_security, owner)[1]
    )


@pytest.mark.parametrize("action", ["other", "current", "all"])
def test_session_revocation_has_precise_scope_and_cookie_confirmation(
    account_security, action
):
    client, owner = account_security.client()
    second, _ = account_security.client()
    foreign, _ = account_security.client("B")
    current = account_security.principal(client)
    target = (
        account_security.principal(second).token_digest
        if action == "other"
        else current.token_digest
    )
    with account_security.world.storage.transaction() as conn:
        sid = str(
            conn.execute(
                "SELECT id FROM app.sessions WHERE token_digest=%s", (target,)
            ).fetchone()[0]
        )
    operation = "sessions_revoke_all" if action == "all" else "session_revoke"
    proof = account_security.proof(client, operation, None if action == "all" else sid)
    route = (
        "/session-revocations"
        if action == "all"
        else "/sessions/" + sid + "/revocations"
    )
    response = client.post(PATH + route, json={"proof_token": proof})
    assert response.status_code == 200 and response.json()[
        "current_session_revoked"
    ] == (action != "other")
    assert client.get(PATH).status_code == (200 if action == "other" else 401)
    assert second.get(PATH).status_code == (200 if action == "current" else 401)
    assert foreign.get(PATH).status_code == 200
    with account_security.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT auth_epoch FROM app.users WHERE id=%s", (owner,)
        ).fetchone() == (int(action == "all"),)
    assert account_security.world.calls == []


def test_capabilities_are_method_and_configuration_specific_no_first_password_add(
    account_security, monkeypatch
):
    linked, _ = account_security.client()
    google_only, _ = account_security.client("B", linked=False)
    caps = linked.get(PATH).json()["capabilities"]
    assert all(
        caps[key]
        for key in (
            "recent_proof",
            "password_change",
            "session_revoke",
            "sessions_revoke_all",
        )
    )
    assert not any(
        caps[key]
        for key in (
            "password_add",
            "google_link",
            "google_unlink",
            "email_change",
            "notification_delivery",
        )
    )
    assert not google_only.get(PATH).json()["capabilities"]["recent_proof"]
    assert (
        google_only.post(
            PATH + "/reauth-challenges", json={"operation": "password_change"}
        ).status_code
        == 403
    )
    monkeypatch.setenv("ACCOUNT_MAIL_ENABLED", "false")
    caps = linked.get(PATH).json()["capabilities"]
    assert (
        not caps["password_change"]
        and caps["recent_proof"]
        and caps["sessions_revoke_all"]
    )


def test_existing_password_feature_gate_does_not_become_a_signup_gate(
    account_security, monkeypatch
):
    from auth.password_settings import get_password_store

    client, _ = account_security.client()
    monkeypatch.delitem(main.app.dependency_overrides, get_password_store)
    monkeypatch.setenv("PASSWORD_REGISTRATION_ENABLED", "false")
    monkeypatch.setenv("PASSWORD_RECOVERY_ENABLED", "false")
    assert (
        client.post(
            PATH + "/reauth-challenges", json={"operation": "password_change"}
        ).status_code
        == 200
    )
    monkeypatch.setenv("PASSWORD_AUTH_ENABLED", "false")
    assert not client.get(PATH).json()["capabilities"]["recent_proof"]
    assert (
        client.post(
            PATH + "/reauth-challenges", json={"operation": "password_change"}
        ).status_code
        == 503
    )
    assert account_security.hasher.calls == []
