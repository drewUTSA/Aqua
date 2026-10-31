"""New identity routes cannot bypass current-cookie CSRF or closed audiences."""

import pytest
from fastapi.testclient import TestClient
from auth.sessions import session_cookie_name
from security_action_fixtures import NEW, PATH

ID = "00000000-0000-4000-8000-000000000001"
TOKEN = "v2." + "t" * 43
TARGET = {"operation": "sessions_revoke_all"}
PROOF = {"proof_token": TOKEN}
MAIL = {**PROOF, "request_id": ID, "request_token": TOKEN, "email_token": "m" * 43}
ACTIONS = [
    ("POST", "/reauth/google-challenges", {**TARGET, "identity_id": ID}),
    (
        "POST",
        "/reauth/google",
        {
            **TARGET,
            "challenge_id": ID,
            "challenge_token": TOKEN,
            "credential": "synthetic",
        },
    ),
    ("POST", "/google-link-challenges", PROOF),
    (
        "POST",
        "/google-link-candidates",
        {"challenge_id": ID, "challenge_token": TOKEN, "credential": "synthetic"},
    ),
    ("POST", "/google-links", {**PROOF, "candidate_token": TOKEN}),
    ("POST", "/methods/google/" + ID + "/revocations", PROOF),
    ("POST", "/password-enrollments", PROOF),
    ("POST", "/password", {**MAIL, "new_password": NEW}),
    ("POST", "/email-change-requests", {**PROOF, "new_email": "new@example.invalid"}),
    ("PUT", "/email", {**MAIL, "old_email_token": "o" * 43}),
    (
        "PUT",
        "/notification-settings",
        {"expectedRevision": 1, "in_app_success": True, "preview": "generic"},
    ),
]


@pytest.mark.parametrize(
    "method,path,body", ACTIONS, ids=[path for _, path, _ in ACTIONS]
)
def test_new_actions_require_current_session_and_csrf(
    identity_security, method, path, body
):
    secure = identity_security
    client, _ = secure.client(linked=False)
    anonymous = TestClient(
        __import__("main").app, base_url=secure.world.settings.app_origin
    )
    assert anonymous.request(method, PATH + path, json=body).status_code == 401
    assert (
        client.request(
            method, PATH + path, json=body, headers={"X-CSRF-Token": "wrong"}
        ).status_code
        == 403
    )
    assert secure.provider_calls == [] and secure.hasher.calls == []
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.account_security_requests"
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM app.account_action_proofs"
        ).fetchone() == (0,)


@pytest.mark.parametrize(
    "method,path,body", ACTIONS, ids=[path for _, path, _ in ACTIONS]
)
def test_new_cookie_with_old_owner_csrf_fails_before_any_sql(
    identity_security, monkeypatch, method, path, body
):
    secure = identity_security
    old, _ = secure.client()
    new, _ = secure.client("B")

    def deny(*args, **kwargs):
        raise AssertionError("SQL before paired-session CSRF rejection")

    monkeypatch.setattr(secure.world.storage, "transaction", deny)
    cookie = session_cookie_name(secure.world.settings)
    response = old.request(
        method,
        PATH + path,
        json=body,
        headers={"Cookie": cookie + "=" + new.cookies.get(cookie)},
    )
    assert (
        response.status_code == 403
        and secure.provider_calls == []
        and secure.hasher.calls == []
    )


@pytest.mark.parametrize(
    "method,path,body", ACTIONS, ids=[path for _, path, _ in ACTIONS]
)
def test_mass_assignment_and_queries_cannot_authorize_new_actions(
    identity_security, method, path, body
):
    secure = identity_security
    client, _ = secure.client()
    for key in ["owner_id", "verified", "auth_epoch"]:
        response = client.request(
            method, PATH + path, json={**body, key: "PRIVATE_AUTHORITY_CANARY"}
        )
        assert (
            response.status_code == 422
            and "PRIVATE_AUTHORITY_CANARY" not in response.text
        )
    assert (
        client.request(method, PATH + path + "?owner_id=forged", json=body).status_code
        == 422
    )
    assert secure.provider_calls == [] and secure.hasher.calls == []


def test_google_credential_duplicate_or_oversize_is_rejected_before_provider(
    identity_security,
):
    secure = identity_security
    client, _ = secure.client()
    body = (
        '{"operation":"sessions_revoke_all","challenge_id":"'
        + ID
        + '","challenge_token":"'
        + TOKEN
        + '","credential":"first","crede\\u006etial":"PRIVATE_DUPLICATE"}'
    )
    response = client.post(
        PATH + "/reauth/google",
        content=body,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422 and "PRIVATE_DUPLICATE" not in response.text
    response = client.post(
        PATH + "/reauth/google",
        content=b" " * 16385,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413 and secure.provider_calls == []


def test_new_action_cookie_settings_are_host_bound_and_private(identity_security):
    secure = identity_security
    client, _ = secure.client(linked=False)
    start = secure.google_start(client)
    assert (
        start["nonce"] and start["client_id"] == secure.world.settings.google_client_id
    )
    response = client.post(
        PATH + "/password-enrollments",
        json={"proof_token": secure.google_proof(client)},
    )
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith("__host-aqua_identity_action=") and all(
        flag in cookie
        for flag in ["httponly", "secure", "samesite=lax", "path=/", "max-age=1800"]
    )
    assert "domain=" not in cookie and response.headers["cache-control"] == "no-store"
