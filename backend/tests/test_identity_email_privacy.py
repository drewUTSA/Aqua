"""An accepted mailbox-change request does not disclose another account."""

from datetime import datetime
import secrets
from uuid import UUID

import pytest

from security_action_fixtures import PATH
from test_identity_methods import account_state


@pytest.mark.parametrize("state", ["free", "other", "self"])
def test_email_change_request_has_one_shape_and_sends_only_for_free_target(
    identity_security, state
):
    secure = identity_security
    client, owner = secure.client()
    foreign, other = secure.client("B")
    target = "synthetic-target@example.invalid"
    occupied = state != "free"
    if state == "other":
        with secure.world.storage.transaction() as conn:
            conn.execute(
                "UPDATE app.user_emails SET address=%s,email_key=%s WHERE user_id=%s",
                (target, target, other),
            )
    elif state == "self":
        with secure.world.storage.transaction() as conn:
            target = conn.execute(
                "SELECT email_key FROM app.user_emails WHERE user_id=%s AND is_primary",
                (owner,),
            ).fetchone()[0]
    before_owner = account_state(secure, owner)
    before_other = account_state(secure, other)
    proof = secure.password_proof(client, "email_change", target)
    response = client.post(
        PATH + "/email-change-requests",
        json={"proof_token": proof, "new_email": target},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "schemaVersion",
        "request_id",
        "request_token",
        "expires_at",
        "confirmation_required",
    }
    assert body["schemaVersion"] == 1
    assert body["confirmation_required"] == "old_and_new_email"
    assert str(UUID(body["request_id"])) == body["request_id"]
    assert body["request_token"].startswith("v2.")
    assert len(body["request_token"]) == 46
    assert datetime.fromisoformat(body["expires_at"]).tzinfo is not None
    assert response.headers["cache-control"] == "no-store"
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.account_security_requests WHERE user_id=%s",
            (owner,),
        ).fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM app.account_mail").fetchone() == (
            0 if occupied else 2,
        )
        assert conn.execute(
            "SELECT count(*) FROM app.auth_challenges WHERE account_request_id=%s",
            (body["request_id"],),
        ).fetchone() == (0 if occupied else 2,)
    # Neither an occupied target nor fabricated confirmation tokens can alter
    # either account; the regular proof and both-mailbox requirements still hold.
    denied = client.put(
        PATH + "/email",
        json={
            "proof_token": proof,
            "request_id": body["request_id"],
            "request_token": body["request_token"],
            "email_token": secrets.token_urlsafe(32),
            "old_email_token": secrets.token_urlsafe(32),
        },
    )
    assert denied.status_code == 403
    assert account_state(secure, owner) == before_owner
    assert account_state(secure, other) == before_other
    assert foreign.get(PATH).status_code == 200


def test_occupied_requests_share_the_pending_request_cap(identity_security):
    secure = identity_security
    client, owner = secure.client()
    _, other = secure.client("B")
    with secure.world.storage.transaction() as conn:
        target = conn.execute(
            "SELECT email_key FROM app.user_emails WHERE user_id=%s AND is_primary",
            (other,),
        ).fetchone()[0]
    proof = secure.password_proof(client, "email_change", target)
    for expected in (200, 200, 200, 429):
        response = client.post(
            PATH + "/email-change-requests",
            json={"proof_token": proof, "new_email": target},
        )
        assert response.status_code == expected, response.text
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.account_security_requests WHERE user_id=%s",
            (owner,),
        ).fetchone() == (3,)
        assert conn.execute("SELECT count(*) FROM app.account_mail").fetchone() == (0,)
