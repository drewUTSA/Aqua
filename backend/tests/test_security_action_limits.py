"""Admission/hash bounds survive worker churn; session writes never scan history."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Event
from uuid import uuid4

import pytest

from account.reauth import RecentAuth
from account.security_actions import SecurityActions
from auth.config import AuthLimited
from auth.passwords import PasswordStore
from auth.sessions import new_token, token_digest
from security_action_fixtures import OLD, PATH
from storage.pool import Storage


def test_durable_action_admission_is_shared_across_storage_instances_and_recovers(
    account_security,
):
    client, owner = account_security.client()
    principal = account_security.principal(client)
    account_security.passwords.auth_policy = replace(
        account_security.passwords.auth_policy, action_account_limit=2
    )
    storage = Storage(account_security.world.storage.settings)
    other = PasswordStore(
        storage,
        account_security.passwords.auth_policy,
        account_security.passwords.policy,
        account_security.passwords.mail_policy,
        hasher=account_security.hasher,
    )
    try:
        for store in (account_security.passwords, other):
            RecentAuth(store).start(
                principal,
                "password_change",
                None,
                token_digest(new_token()),
                token_digest(new_token()),
            )
        with pytest.raises(AuthLimited):
            RecentAuth(other).start(
                principal,
                "password_change",
                None,
                token_digest(new_token()),
                token_digest(new_token()),
            )
        with account_security.world.storage.transaction() as conn:
            assert conn.execute(
                "SELECT hits FROM app.auth_admission WHERE scope='action:account'"
            ).fetchone() == (2,)
            conn.execute(
                "UPDATE app.auth_admission SET expires_at=now()-interval '1 second' WHERE scope LIKE 'action:%'"
            )
        RecentAuth(other).start(
            principal,
            "password_change",
            None,
            token_digest(new_token()),
            token_digest(new_token()),
        )
        with account_security.world.storage.transaction() as conn:
            assert conn.execute(
                "SELECT count(*) FROM app.auth_challenges WHERE user_id=%s AND account_operation IS NOT NULL",
                (owner,),
            ).fetchone() == (3,)
    finally:
        storage.close()


@pytest.mark.parametrize("scope", ["account", "global"])
def test_google_only_challenge_denials_spend_default_budgets_without_allocating_work(
    account_security, scope
):
    account_security.passwords.auth_policy = replace(
        account_security.passwords.auth_policy,
        action_account_limit=5,
        action_global_limit=30,
    )
    if scope == "account":
        # Every request uses another genuine cookie for the same Google-only
        # account; session churn cannot refill its shared five-attempt allowance.
        clients = [account_security.client(linked=False)[0] for _ in range(5)]
        clients.append(clients[0])
    else:
        # Six owners spend five attempts each; the seventh cannot create a new
        # counter after the shared thirty-attempt allowance is exhausted.
        owners = [
            account_security.client(str(index), linked=False)[0] for index in range(7)
        ]
        clients = [client for client in owners[:6] for _ in range(5)] + owners[6:]
    for client in clients[:-1]:
        response = client.post(
            PATH + "/reauth-challenges", json={"operation": "password_change"}
        )
        assert (
            response.status_code == 403
            and response.json()["error"]["code"] == "method_unavailable"
        )
        assert "set-cookie" not in response.headers
    response = clients[-1].post(
        PATH + "/reauth-challenges", json={"operation": "password_change"}
    )
    assert (
        response.status_code == 429 and 1 <= int(response.headers["retry-after"]) <= 60
    )
    with account_security.world.storage.transaction() as conn:
        rows = conn.execute(
            "SELECT scope,hits FROM app.auth_admission WHERE scope LIKE 'action:%' ORDER BY scope"
        ).fetchall()
        assert rows == (
            [("action:account", 5)] * (1 if scope == "account" else 6)
            + [("action:global", 5 if scope == "account" else 30)]
        )
        assert conn.execute(
            "SELECT count(*) FROM app.auth_challenges WHERE account_operation IS NOT NULL"
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM app.account_action_proofs"
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM app.password_credentials"
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM app.password_hash_slots"
        ).fetchone() == (0,)
    assert account_security.hasher.calls == [] and account_security.world.calls == []


def test_hash_saturation_consumes_attempt_without_verifying_and_recovers_safely(
    account_security,
):
    client, _ = account_security.client()
    challenge = account_security.challenge(client)
    with account_security.world.storage.transaction() as conn:
        for _ in range(2):
            conn.execute(
                "INSERT INTO app.password_hash_slots(id) VALUES(%s)", (uuid4(),)
            )
    body = {
        "operation": "password_change",
        "challenge_id": challenge["challenge_id"],
        "challenge_token": challenge["challenge_token"],
        "password": OLD,
    }
    response = client.post(PATH + "/reauth/password", json=body)
    assert (
        response.status_code == 429
        and response.headers["retry-after"] == "1"
        and account_security.hasher.calls == []
    )
    with account_security.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT consumed_at IS NOT NULL FROM app.auth_challenges WHERE id=%s",
            (challenge["challenge_id"],),
        ).fetchone() == (True,)
        conn.execute("DELETE FROM app.password_hash_slots")
    assert client.post(PATH + "/reauth/password", json=body).status_code == 403
    assert account_security.proof(client) and account_security.hasher.calls == [
        "verify"
    ]


def test_hash_failure_is_redacted_releases_slots_and_requires_fresh_challenge(
    account_security, caplog
):
    from auth.config import AuthDenied

    client, _ = account_security.client()
    challenge = account_security.challenge(client)

    def fail():
        raise AuthDenied("PRIVATE_ACCOUNT_HASH_CANARY " + OLD)

    account_security.hasher.on_verify = fail
    body = {
        "operation": "password_change",
        "challenge_id": challenge["challenge_id"],
        "challenge_token": challenge["challenge_token"],
        "password": OLD,
    }
    response = client.post(PATH + "/reauth/password", json=body)
    assert response.status_code == 503
    for secret in ("PRIVATE_ACCOUNT_HASH_CANARY", OLD, challenge["challenge_token"]):
        assert secret not in response.text and secret not in caplog.text
    with account_security.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.password_hash_slots"
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT consumed_at IS NOT NULL FROM app.auth_challenges WHERE id=%s",
            (challenge["challenge_id"],),
        ).fetchone() == (True,)
    account_security.hasher.on_verify = None
    assert client.post(PATH + "/reauth/password", json=body).status_code == 403
    assert account_security.proof(client)


def test_two_detached_hash_jobs_bound_work_across_pools_and_release_slots(
    account_security,
):
    client, _ = account_security.client()
    principal = account_security.principal(client)
    storages = [
        Storage(
            replace(
                account_security.world.storage.settings, max_waiting=2, wait_seconds=2
            )
        )
        for _ in range(2)
    ]
    stores = [
        PasswordStore(
            storage,
            account_security.passwords.auth_policy,
            account_security.passwords.policy,
            account_security.passwords.mail_policy,
            hasher=account_security.hasher,
        )
        for storage in storages
    ]
    inputs = []
    for store in [*stores, account_security.passwords]:
        secret, binding = token_digest(new_token()), token_digest(new_token())
        challenge = RecentAuth(store).start(
            principal, "password_change", None, secret, binding
        )
        inputs.append((store, challenge["challenge_id"], secret, binding))
    entered, release = Barrier(3), Event()

    def hold():
        entered.wait(timeout=4)
        assert release.wait(timeout=5)

    account_security.hasher.on_verify = hold

    def verify(values):
        store, challenge, secret, binding = values
        return RecentAuth(store).password(
            principal, challenge, "password_change", None, secret, binding, OLD
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            futures = [workers.submit(verify, values) for values in inputs[:2]]
            try:
                entered.wait(timeout=4)
                with pytest.raises(AuthLimited):
                    verify(inputs[2])
                with account_security.world.storage.transaction() as conn:
                    assert conn.execute(
                        "SELECT count(*) FROM app.password_hash_slots"
                    ).fetchone() == (2,)
            finally:
                release.set()
            assert all(future.result(timeout=5)["proof_token"] for future in futures)
        with account_security.world.storage.transaction() as conn:
            assert conn.execute(
                "SELECT count(*) FROM app.password_hash_slots"
            ).fetchone() == (0,)
    finally:
        for storage in storages:
            storage.close()


@pytest.mark.parametrize("live_count", [20, 21])
def test_revoke_all_bounds_live_writes_and_preserves_large_expired_history(
    account_security, live_count
):
    client, owner = account_security.client()
    principal = account_security.principal(client)
    proof = account_security.proof(client, "sessions_revoke_all")
    with account_security.world.storage.transaction() as conn:
        conn.execute(
            "INSERT INTO app.sessions(user_id,token_digest,csrf_digest,auth_epoch,method,created_at,idle_expires_at,absolute_expires_at) SELECT %s,decode(md5('p10b-expired-'||n::text)||md5('p10b-expired-tail-'||n::text),'hex'),%s,0,'password',now()-interval '2 hours',now()-interval '1 hour',now()+interval '1 hour' FROM generate_series(1,5000)n",
            (owner, b"c" * 32),
        )
        conn.execute(
            "INSERT INTO app.sessions(user_id,token_digest,csrf_digest,auth_epoch,method,idle_expires_at,absolute_expires_at) SELECT %s,decode(md5('p10b-live-'||n::text)||md5('p10b-live-tail-'||n::text),'hex'),%s,0,'password',now()+interval '10 minutes',now()+interval '1 hour' FROM generate_series(1,%s)n",
            (owner, b"c" * 32, live_count - 1),
        )
    response = client.post(PATH + "/session-revocations", json={"proof_token": proof})
    assert response.status_code == (200 if live_count == 20 else 503)
    with account_security.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.sessions WHERE user_id=%s AND revoked_at IS NOT NULL",
            (owner,),
        ).fetchone() == (20 if live_count == 20 else 0,)
        assert conn.execute(
            "SELECT count(*) FROM app.sessions WHERE user_id=%s AND idle_expires_at<=now() AND revoked_at IS NULL",
            (owner,),
        ).fetchone() == (5000,)
        assert conn.execute(
            "SELECT auth_epoch FROM app.users WHERE id=%s", (owner,)
        ).fetchone() == (int(live_count == 20),)
        assert conn.execute(
            "SELECT consumed_at IS NOT NULL FROM app.account_action_proofs WHERE secret_digest=%s",
            (token_digest(proof),),
        ).fetchone() == (live_count == 20,)
    if live_count == 20:
        from workspace.errors import WorkspaceError

        with pytest.raises(WorkspaceError):
            SecurityActions(account_security.passwords).session(
                principal, None, token_digest(proof)
            )
