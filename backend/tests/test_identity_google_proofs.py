"""Fresh signed-provider assertions bind one exact owned active method revision."""

import time
from dataclasses import replace
import pytest
from analysis import streams
from auth.accounts import grant_state
from account.security_http import binding_cookie
from auth.sessions import token_digest
from workspace.errors import WorkspaceError
from security_action_fixtures import PATH


def verification(start, credential, operation="password_add"):
    return {
        "operation": operation,
        "challenge_id": start["challenge_id"],
        "challenge_token": start["challenge_token"],
        "credential": credential,
    }


def test_google_only_recent_proof_is_password_flag_independent_and_not_a_login(
    identity_security, monkeypatch
):
    secure = identity_security
    client, owner = secure.client(linked=False)
    monkeypatch.setenv("PASSWORD_AUTH_ENABLED", "false")
    proof = secure.google_proof(client, "sessions_revoke_all")
    with secure.world.storage.transaction() as conn:
        row = conn.execute(
            "SELECT method,external_identity_revision,extract(epoch FROM expires_at-created_at),secret_digest FROM app.account_action_proofs WHERE user_id=%s",
            (owner,),
        ).fetchone()
        assert (
            row[0:2] == ("google", 1)
            and 0 < row[2] <= 300
            and bytes(row[3]) == token_digest(proof)
        )
        assert conn.execute(
            "SELECT count(*) FROM app.sessions WHERE user_id=%s", (owner,)
        ).fetchone() == (1,)
    assert secure.hasher.calls == [] and len(secure.provider_calls) == 1
    assert (
        client.post(
            PATH + "/session-revocations", json={"proof_token": proof}
        ).status_code
        == 200
    )
    assert client.get(PATH).status_code == 401


@pytest.mark.parametrize(
    "change",
    [
        "nonce",
        "aud",
        "issuer",
        "email_verified",
        "subject",
        "iat_bool",
        "iat_float",
        "iat_old",
        "iat_future",
        "iat_missing",
    ],
)
def test_invalid_google_assertion_burns_challenge_without_issuing_proof(
    identity_security, change
):
    secure = identity_security
    client, _ = secure.client(linked=False)
    start = secure.google_start(client)
    changes = {
        "nonce": {"nonce": "different"},
        "aud": {"aud": "foreign-client"},
        "issuer": {"iss": "https://foreign.invalid"},
        "email_verified": {"email_verified": False},
        "subject": {"sub": "another-subject"},
        "iat_bool": {"iat": True},
        "iat_float": {"iat": float(time.time())},
        "iat_old": {"iat": int(time.time()) - 301},
        "iat_future": {"iat": int(time.time()) + 31},
        "iat_missing": {"iat": None},
    }[change]
    credential = secure.assertion(start["nonce"], **changes)
    body = verification(start, credential)
    assert client.post(PATH + "/reauth/google", json=body).status_code == 403
    assert client.post(PATH + "/reauth/google", json=body).status_code == 403
    assert len(secure.provider_calls) == 1 and secure.hasher.calls == []
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.account_action_proofs"
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT consumed_at IS NOT NULL FROM app.auth_challenges WHERE id=%s",
            (start["challenge_id"],),
        ).fetchone() == (True,)


@pytest.mark.parametrize(
    "change", ["revision", "deactivate", "reactivate", "epoch", "session", "expiry"]
)
def test_authority_changes_during_detached_google_verification_deny(
    identity_security, change
):
    secure = identity_security
    client, owner = secure.client(linked=False)
    principal = secure.principal(client)
    start = secure.google_start(client)

    def mutate():
        with secure.world.storage.transaction() as conn:
            if change in {"revision", "deactivate", "reactivate"}:
                conn.execute(
                    "UPDATE app.external_identities SET revision=revision+1,is_active=false,inactive_at=now() WHERE user_id=%s",
                    (owner,),
                )
                if change != "deactivate":
                    conn.execute(
                        "UPDATE app.external_identities SET is_active=true,inactive_at=NULL,revision=revision+1 WHERE user_id=%s",
                        (owner,),
                    )
            elif change == "epoch":
                conn.execute(
                    "UPDATE app.users SET auth_epoch=auth_epoch+1 WHERE id=%s", (owner,)
                )
            elif change == "session":
                conn.execute(
                    "UPDATE app.sessions SET revoked_at=now() WHERE token_digest=%s",
                    (principal.token_digest,),
                )
            else:
                conn.execute(
                    "UPDATE app.auth_challenges SET created_at=now()-interval '5 minutes',expires_at=now()-interval '1 second' WHERE id=%s",
                    (start["challenge_id"],),
                )

    secure.on_google = mutate
    response = client.post(
        PATH + "/reauth/google",
        json=verification(start, secure.assertion(start["nonce"])),
    )
    assert response.status_code in {401, 403}
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.account_action_proofs"
        ).fetchone() == (0,)


@pytest.mark.parametrize(
    "change", ["binding", "foreign_identity", "other_owner", "password_challenge"]
)
def test_wrong_google_challenge_cannot_start_provider_work(identity_security, change):
    secure = identity_security
    client, _ = secure.client()
    other, _ = secure.client("B", linked=False)
    start = secure.google_start(client, "sessions_revoke_all")
    credential = secure.assertion(start["nonce"])
    if change == "foreign_identity":
        with secure.world.storage.transaction() as conn:
            identity = str(
                conn.execute(
                    "SELECT id FROM app.external_identities WHERE subject='workspace-B'"
                ).fetchone()[0]
            )
        assert (
            client.post(
                PATH + "/reauth/google-challenges",
                json={"operation": "sessions_revoke_all", "identity_id": identity},
            ).status_code
            == 403
        )
        return
    if change == "binding":
        client.cookies.delete(
            binding_cookie(secure.world.settings), domain="workspace.fixture", path="/"
        )
    if change == "password_challenge":
        raw = client.post(
            PATH + "/reauth-challenges", json={"operation": "sessions_revoke_all"}
        ).json()
        start = {**start, **raw}
    candidate = other if change == "other_owner" else client
    assert (
        candidate.post(
            PATH + "/reauth/google",
            json=verification(start, credential, "sessions_revoke_all"),
        ).status_code
        == 403
    )
    assert secure.provider_calls == []


def test_google_only_denials_use_default_durable_account_allowance(identity_security):
    secure = identity_security
    client, _ = secure.client(linked=False)
    secure.passwords.auth_policy = replace(
        secure.passwords.auth_policy, action_account_limit=5, action_global_limit=30
    )
    foreign = str(__import__("uuid").uuid4())
    for _ in range(5):
        assert (
            client.post(
                PATH + "/reauth/google-challenges",
                json={"operation": "password_add", "identity_id": foreign},
            ).status_code
            == 403
        )
    assert (
        client.post(
            PATH + "/reauth/google-challenges",
            json={"operation": "password_add", "identity_id": foreign},
        ).status_code
        == 429
    )
    assert secure.provider_calls == []
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT hits FROM app.auth_admission WHERE scope='action:account'"
        ).fetchone() == (5,)
        assert conn.execute(
            "SELECT count(*) FROM app.auth_challenges WHERE account_operation IS NOT NULL"
        ).fetchone() == (0,)


@pytest.mark.parametrize("change", ["different_email", "lost_authoritativeness"])
def test_verified_google_observation_fences_existing_email_grant_without_profile_or_operator_change(
    identity_security, monkeypatch, change
):
    secure = identity_security
    client, owner = secure.client(linked=False)
    _, foreign = secure.client("B", linked=False)
    original_email = (
        "a@gmail.com"
        if change == "different_email"
        else "old@workspace.example.invalid"
    )
    fresh_email = "B@GMAIL.COM" if change == "different_email" else original_email
    policy = replace(secure.world.policy, allowed_emails=frozenset({original_email}))
    secure.world.policy = policy
    secure.world.store.policy = policy
    secure.world.analysis.policy = policy
    secure.passwords.auth_policy = replace(
        secure.passwords.auth_policy, allowed_emails=policy.allowed_emails
    )
    secure.world.settings = replace(
        secure.world.settings, auth_allowed_emails=policy.allowed_emails
    )
    monkeypatch.setattr(__import__("main").app.state, "settings", secure.world.settings)
    # Keep the existing explicit fake analysis seam paired with the settings
    # generation. A mismatch makes get_analysis create a live dispatcher.
    secure.world.analysis.settings = secure.world.settings
    assert secure.world.analysis.threads == []
    with secure.world.storage.transaction() as conn:
        identity = conn.execute(
            "SELECT id FROM app.external_identities WHERE user_id=%s", (owner,)
        ).fetchone()[0]
        conn.execute(
            "UPDATE app.external_identities SET observed_email_key=%s,email_authoritative=true WHERE id=%s",
            (original_email, identity),
        )
        conn.execute(
            "INSERT INTO app.dataset_grants(user_id,dataset_key,approval_kind,approval_identity_id,approval_evidence) VALUES(%s,%s,'google_email',%s,%s)",
            (owner, policy.dataset_key, identity, original_email),
        )
        conn.execute(
            "INSERT INTO app.dataset_grants(user_id,dataset_key) VALUES(%s,'operator-preserved')",
            (owner,),
        )
        conn.execute(
            "INSERT INTO app.dataset_grants(user_id,dataset_key,approval_kind,approval_identity_id,approval_evidence,revoked_at) VALUES(%s,'revoked-derived','google_email',%s,%s,now())",
            (owner, identity, original_email),
        )
        original = conn.execute(
            "SELECT display_name,picture,profile_revision,email_revision,auth_epoch FROM app.users WHERE id=%s",
            (owner,),
        ).fetchone()
        primary = conn.execute(
            "SELECT id,email_key,is_primary FROM app.user_emails WHERE user_id=%s ORDER BY id",
            (owner,),
        ).fetchall()
        grants = conn.execute(
            "SELECT dataset_key,version,granted_at,revoked_at,approval_kind,approval_identity_id,approval_evidence FROM app.dataset_grants WHERE user_id=%s ORDER BY dataset_key",
            (owner,),
        ).fetchall()
        foreign_before = conn.execute(
            "SELECT id,user_id,observed_email_key,email_authoritative FROM app.external_identities WHERE user_id=%s",
            (foreign,),
        ).fetchall()
        assert grant_state(conn, owner, policy)[0]
    saved = client.post("/api/v1/chats", json=secure.world.body())
    assert saved.status_code == 202, saved.text
    assert __import__("main").app.state.analysis is secure.world.analysis
    assert secure.world.analysis.threads == []
    request_id = saved.json()["request"]["id"]
    principal = secure.principal(client)
    stream_id = streams.acquire(secure.world.analysis, principal, request_id)
    try:
        start = secure.google_start(client, "sessions_revoke_all")
        credential = secure.assertion(start["nonce"], email=fresh_email)
        assert (
            client.post(
                PATH + "/reauth/google",
                json=verification(start, credential, "sessions_revoke_all"),
            ).status_code
            == 200
        )
        with secure.world.storage.transaction() as conn:
            assert conn.execute(
                "SELECT observed_email_key,email_authoritative FROM app.external_identities WHERE id=%s",
                (identity,),
            ).fetchone() == (fresh_email.lower(), change == "different_email")
            assert not grant_state(conn, owner, policy)[0]
            assert (
                conn.execute(
                    "SELECT display_name,picture,profile_revision,email_revision,auth_epoch FROM app.users WHERE id=%s",
                    (owner,),
                ).fetchone()
                == original
            )
            assert (
                conn.execute(
                    "SELECT id,email_key,is_primary FROM app.user_emails WHERE user_id=%s ORDER BY id",
                    (owner,),
                ).fetchall()
                == primary
            )
            assert (
                conn.execute(
                    "SELECT dataset_key,version,granted_at,revoked_at,approval_kind,approval_identity_id,approval_evidence FROM app.dataset_grants WHERE user_id=%s ORDER BY dataset_key",
                    (owner,),
                ).fetchall()
                == grants
            )
            assert (
                conn.execute(
                    "SELECT id,user_id,observed_email_key,email_authoritative FROM app.external_identities WHERE user_id=%s",
                    (foreign,),
                ).fetchall()
                == foreign_before
            )
        assert client.post("/api/v1/chats", json=secure.world.body()).status_code == 403
        assert client.get("/api/v1/analysis-requests/" + request_id).status_code == 403
        with pytest.raises(WorkspaceError) as denied:
            streams.batch(secure.world.analysis, principal, request_id, stream_id, 0)
        assert denied.value.status == 403 and secure.world.calls == []
    finally:
        streams.release(secure.world.analysis, stream_id)


def test_invalid_google_nonce_cannot_publish_new_email_observation(identity_security):
    secure = identity_security
    client, owner = secure.client(linked=False)
    with secure.world.storage.transaction() as conn:
        before = conn.execute(
            "SELECT observed_email_key,email_authoritative,revision,last_login_at FROM app.external_identities WHERE user_id=%s",
            (owner,),
        ).fetchone()
    start = secure.google_start(client)
    credential = secure.assertion(
        "wrong-action-nonce", email="different@example.invalid"
    )
    assert (
        client.post(
            PATH + "/reauth/google", json=verification(start, credential)
        ).status_code
        == 403
    )
    with secure.world.storage.transaction() as conn:
        assert (
            conn.execute(
                "SELECT observed_email_key,email_authoritative,revision,last_login_at FROM app.external_identities WHERE user_id=%s",
                (owner,),
            ).fetchone()
            == before
        )
        assert conn.execute(
            "SELECT count(*) FROM app.account_action_proofs"
        ).fetchone() == (0,)
