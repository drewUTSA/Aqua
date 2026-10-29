"""Independent bounded pools serialize proof/method/session changes by owner."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest

from account.reauth import RecentAuth
from account.security_actions import SecurityActions
from auth.config import AuthDenied
from auth.passwords import PasswordStore
from auth.sessions import token_digest
from storage.pool import Storage
from workspace.errors import WorkspaceError
from security_action_fixtures import NEW, OLD
from test_security_action_failures import seed_reset


def second_store(account_security):
    storage = Storage(
        replace(account_security.world.storage.settings, max_waiting=2, wait_seconds=2)
    )
    store = PasswordStore(
        storage,
        account_security.passwords.auth_policy,
        account_security.passwords.policy,
        account_security.passwords.mail_policy,
        hasher=account_security.hasher,
    )
    return storage, store


def test_parallel_claim_has_one_verifier_and_one_issued_proof(account_security):
    client, owner = account_security.client()
    principal = account_security.principal(client)
    from auth.sessions import new_token

    secret, binding = token_digest(new_token()), token_digest(new_token())
    challenge = RecentAuth(account_security.passwords).start(
        principal, "password_change", None, secret, binding
    )
    storage, other = second_store(account_security)
    ready = Barrier(2)

    def attempt(store):
        ready.wait(timeout=3)
        try:
            RecentAuth(store).password(
                principal,
                challenge["challenge_id"],
                "password_change",
                None,
                secret,
                binding,
                OLD,
            )
            return "issued"
        except WorkspaceError:
            return "denied"

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            assert sorted(
                workers.map(attempt, [account_security.passwords, other])
            ) == [
                "denied",
                "issued",
            ]
        assert account_security.hasher.calls == ["verify"]
        with account_security.world.storage.transaction() as conn:
            assert conn.execute(
                "SELECT count(*) FROM app.account_action_proofs WHERE user_id=%s",
                (owner,),
            ).fetchone() == (1,)
    finally:
        storage.close()


def test_parallel_password_change_has_one_commit_one_notice_no_foreign_changes(
    account_security,
):
    client, owner = account_security.client()
    _, foreign = account_security.client("B")
    proof = account_security.proof(client)
    principal = account_security.principal(client)
    storage, other = second_store(account_security)
    hashes = Barrier(2)
    account_security.hasher.on_hash = lambda: hashes.wait(timeout=3)

    def attempt(store):
        try:
            SecurityActions(store).password(principal, token_digest(proof), NEW)
            return "changed"
        except WorkspaceError:
            return "denied"

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            assert sorted(
                workers.map(attempt, [account_security.passwords, other])
            ) == [
                "changed",
                "denied",
            ]
        with account_security.world.storage.transaction() as conn:
            assert conn.execute(
                "SELECT auth_epoch FROM app.users WHERE id=%s", (owner,)
            ).fetchone() == (1,)
            assert conn.execute(
                "SELECT auth_epoch FROM app.users WHERE id=%s", (foreign,)
            ).fetchone() == (0,)
            assert conn.execute(
                "SELECT count(*) FROM app.account_mail WHERE purpose='password_changed'"
            ).fetchone() == (1,)
            assert conn.execute(
                "SELECT count(*) FROM app.password_hash_slots"
            ).fetchone() == (0,)
    finally:
        storage.close()


def test_reset_and_authenticated_change_share_mail_before_user_lock_order(
    account_security,
):
    client, owner = account_security.client()
    reset_token, _ = seed_reset(account_security, owner)
    proof = account_security.proof(client)
    principal = account_security.principal(client)
    storage, other = second_store(account_security)
    hashes = Barrier(2)
    account_security.hasher.on_hash = lambda: hashes.wait(timeout=3)

    def change():
        try:
            SecurityActions(account_security.passwords).password(
                principal, token_digest(proof), NEW
            )
            return "changed"
        except WorkspaceError:
            return "denied"

    def reset():
        try:
            other.reset_password(
                reset_token, "A distinct synthetic reset password 64", "fixture"
            )
            return "reset"
        except AuthDenied:
            return "denied"

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            left, right = workers.submit(change), workers.submit(reset)
            outcomes = [left.result(timeout=6), right.result(timeout=6)]
        assert outcomes.count("denied") == 1
        with account_security.world.storage.transaction() as conn:
            assert conn.execute(
                "SELECT auth_epoch FROM app.users WHERE id=%s", (owner,)
            ).fetchone() == (1,)
            assert conn.execute(
                "SELECT count(*) FROM app.account_mail WHERE purpose='password_changed'"
            ).fetchone() == (1,)
    finally:
        storage.close()


@pytest.mark.parametrize("all_sessions", [False, True])
def test_parallel_revocation_can_commit_only_once_across_pools(
    account_security, all_sessions
):
    client, owner = account_security.client()
    other_client, _ = account_security.client()
    principal = account_security.principal(client)
    other_principal = account_security.principal(other_client)
    with account_security.world.storage.transaction() as conn:
        sid = str(
            conn.execute(
                "SELECT id FROM app.sessions WHERE token_digest=%s",
                (other_principal.token_digest,),
            ).fetchone()[0]
        )
    target = None if all_sessions else sid
    proof = account_security.proof(
        client, "sessions_revoke_all" if all_sessions else "session_revoke", target
    )
    storage, other = second_store(account_security)
    ready = Barrier(2)

    def attempt(store):
        ready.wait(timeout=3)
        try:
            SecurityActions(store).session(principal, target, token_digest(proof))
            return "revoked"
        except WorkspaceError:
            return "denied"

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            assert sorted(
                workers.map(attempt, [account_security.passwords, other])
            ) == [
                "denied",
                "revoked",
            ]
        with account_security.world.storage.transaction() as conn:
            assert conn.execute(
                "SELECT auth_epoch FROM app.users WHERE id=%s", (owner,)
            ).fetchone() == (int(all_sessions),)
    finally:
        storage.close()
