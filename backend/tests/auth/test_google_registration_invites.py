"""Exercise first-time Google enrollment through the regular signed-in flow."""

import pytest

from auth.config import load_auth_policy
from nl2sql.config import Settings
from _auth_test_helpers import EMAIL
from _durable_route_helpers import SESSION, TOKEN, challenge, headers, login

SETTING = "AUTH_GOOGLE_REGISTRATION_INVITES"


def account_counts(storage):
    with storage.transaction() as conn:
        return conn.execute(
            "SELECT (SELECT count(*) FROM app.users), "
            "(SELECT count(*) FROM app.external_identities), "
            "(SELECT count(*) FROM app.user_emails), "
            "(SELECT count(*) FROM app.dataset_grants), "
            "(SELECT count(*) FROM app.sessions)"
        ).fetchone()


@pytest.mark.parametrize(
    ("invites", "address"),
    [
        ("", EMAIL),
        ("another@gmail.com", EMAIL),
        ("listed@example.test", "listed@example.test"),
    ],
)
def test_uninvited_or_non_authoritative_new_mailbox_creates_no_account(
    durable_browser, monkeypatch, invites, address
):
    client, claims, _, storage = durable_browser
    monkeypatch.setenv(SETTING, invites)
    claims["email"] = address
    before = account_counts(storage)
    config, _ = challenge(durable_browser)
    response = client.post(
        "/api/auth/google",
        json={"credential": TOKEN},
        headers=headers(config["csrf_token"]),
    )
    assert response.status_code == 401
    assert address not in response.text
    assert not client.cookies.get(SESSION)
    assert account_counts(storage) == before


@pytest.mark.parametrize(
    ("address", "hosted_domain"),
    [("invited@gmail.com", None), ("employee@aqua.example", "aqua.example")],
)
def test_invited_new_account_gets_no_implicit_data_grant_and_can_return(
    durable_browser, monkeypatch, address, hosted_domain
):
    client, claims, _, storage = durable_browser
    claims["email"] = address
    if hosted_domain:
        claims["hd"] = hosted_domain
    monkeypatch.setenv(SETTING, " , ".join([address.upper(), "another@gmail.com"]))
    first, _ = login(durable_browser)
    assert first["can_query"] is False
    assert client.post(
        "/api/auth/logout", headers=headers(first["csrf_token"])
    ).status_code in (200, 204)
    monkeypatch.setenv(SETTING, "")
    second, _ = login(durable_browser)
    assert second["user"]["id"] == first["user"]["id"] and second["can_query"] is False
    assert account_counts(storage)[:4] == (1, 1, 1, 0)


def test_missing_blank_and_invalid_configurations_are_distinct():
    settings = Settings()
    assert load_auth_policy(settings, {}).google_registration_invites is None
    assert (
        load_auth_policy(settings, {SETTING: ""}).google_registration_invites
        == frozenset()
    )
    for invalid in ("domain-only", "customer@gmail.com,", "*@example.test"):
        with pytest.raises(
            ValueError, match="authentication_configuration_invalid"
        ) as problem:
            load_auth_policy(settings, {SETTING: invalid})
        assert invalid not in str(problem.value)
