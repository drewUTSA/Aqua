"""Explicit method ownership, grant provenance and last-method concurrency."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest

from account.google_methods import GoogleMethods
from account.security_http import identity_cookie
from auth.passwords import PasswordStore
from auth.sessions import token_digest
from storage.pool import Storage
from workspace.errors import WorkspaceError
from security_action_fixtures import PATH


def account_state(secure, owner):
    with secure.world.storage.transaction() as conn:
        return (
            conn.execute(
                "SELECT display_name,profile_revision,auth_epoch,email_revision FROM app.users WHERE id=%s",
                (owner,),
            ).fetchone(),
            conn.execute(
                "SELECT email_key,is_primary FROM app.user_emails WHERE user_id=%s ORDER BY email_key",
                (owner,),
            ).fetchall(),
            conn.execute(
                "SELECT id,is_active,revision FROM app.external_identities WHERE user_id=%s ORDER BY id",
                (owner,),
            ).fetchall(),
        )


def test_owned_method_email_is_bounded_observation_without_internal_claims(
    identity_security,
):
    secure = identity_security
    client, owner = secure.client()
    _, foreign = secure.client("B")
    response = client.get(PATH + "/methods")
    method = response.json()["google"]["identities"][0]
    assert (
        set(method) == {"id", "linked_at", "email"} and method["email"] == "a@gmail.com"
    )
    for secret in [
        "workspace-A",
        "workspace-B",
        "observed_email_key",
        "issuer",
        "subject",
        "b@gmail.com",
    ]:
        assert secret not in response.text
    with secure.world.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.external_identities SET observed_email_key=%s WHERE user_id=%s",
            ("unsafe\u202e@example.invalid", owner),
        )
    result = client.get(PATH + "/methods")
    assert (
        result.json()["google"]["identities"][0]["email"] is None
        and "unsafe" not in result.text
    )


def test_link_proves_both_methods_costs_five_calls_and_never_merges_matching_email(
    identity_security,
):
    secure = identity_security
    client, owner = secure.client()
    _, foreign = secure.client("B")
    foreign_before = account_state(secure, foreign)
    secure.passwords.auth_policy = replace(
        secure.passwords.auth_policy, action_account_limit=5, action_global_limit=30
    )
    proof = secure.password_proof(client, "google_link")
    candidate = secure.candidate(client, proof, email="b@gmail.com")
    response = client.post(
        PATH + "/google-links",
        json={"proof_token": proof, "candidate_token": candidate},
    )
    assert response.status_code == 200 and response.json()["current_session_revoked"]
    assert (
        client.get(PATH).status_code == 401
        and account_state(secure, foreign) == foreign_before
    )
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT email_key FROM app.user_emails WHERE user_id=%s AND is_primary",
            (owner,),
        ).fetchone() == ("a@gmail.com",)
        assert conn.execute(
            "SELECT count(*) FROM app.external_identities WHERE user_id=%s AND is_active",
            (owner,),
        ).fetchone() == (2,)
        assert conn.execute(
            "SELECT count(*) FROM app.dataset_grants WHERE user_id=%s", (owner,)
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT hits FROM app.auth_admission WHERE scope='action:account'"
        ).fetchall() == [(5,)]
        assert conn.execute("SELECT purpose FROM app.account_mail").fetchall() == [
            ("google_linked",)
        ]
    assert len(secure.provider_calls) == 1 and secure.hasher.calls == ["verify"]


def test_identity_owned_elsewhere_conflicts_without_consuming_either_authority(
    identity_security,
):
    secure = identity_security
    client, owner = secure.client()
    _, foreign = secure.client("B")
    before = (account_state(secure, owner), account_state(secure, foreign))
    proof = secure.password_proof(client, "google_link")
    candidate = secure.candidate(
        client, proof, subject="workspace-B", email="b@gmail.com"
    )
    assert (
        client.post(
            PATH + "/google-links",
            json={"proof_token": proof, "candidate_token": candidate},
        ).status_code
        == 409
    )
    assert (account_state(secure, owner), account_state(secure, foreign)) == before
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT consumed_at IS NULL FROM app.account_action_proofs WHERE secret_digest=%s",
            (token_digest(proof),),
        ).fetchone() == (True,)
        assert conn.execute(
            "SELECT consumed_at IS NULL FROM app.account_security_requests WHERE secret_digest=%s",
            (token_digest(candidate),),
        ).fetchone() == (True,)
        assert conn.execute("SELECT count(*) FROM app.account_mail").fetchone() == (0,)


def test_reactivation_revokes_legacy_derived_grants_and_never_touches_operator_grants(
    identity_security,
):
    secure = identity_security
    client, owner = secure.client()
    with secure.world.storage.transaction() as conn:
        identity = conn.execute(
            "SELECT id FROM app.external_identities WHERE user_id=%s", (owner,)
        ).fetchone()[0]
        conn.execute(
            "UPDATE app.external_identities SET is_active=false,inactive_at=now(),revision=3 WHERE id=%s",
            (identity,),
        )
        conn.execute(
            "INSERT INTO app.dataset_grants(user_id,dataset_key,approval_kind,approval_identity_id,approval_evidence) VALUES(%s,'legacy-derived','google_subject',%s,'workspace-A')",
            (owner, identity),
        )
        conn.execute(
            "INSERT INTO app.dataset_grants(user_id,dataset_key) VALUES(%s,'operator-preserved')",
            (owner,),
        )
        operator = conn.execute(
            "SELECT version,granted_at,revoked_at,approval_kind FROM app.dataset_grants WHERE user_id=%s AND dataset_key='operator-preserved'",
            (owner,),
        ).fetchone()
    proof = secure.password_proof(client, "google_link")
    candidate = secure.candidate(
        client, proof, subject="workspace-A", email="a@gmail.com"
    )
    assert (
        client.post(
            PATH + "/google-links",
            json={"proof_token": proof, "candidate_token": candidate},
        ).status_code
        == 200
    )
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT is_active,revision FROM app.external_identities WHERE id=%s",
            (identity,),
        ).fetchone() == (True, 4)
        assert conn.execute(
            "SELECT revoked_at IS NOT NULL,version FROM app.dataset_grants WHERE user_id=%s AND dataset_key='legacy-derived'",
            (owner,),
        ).fetchone() == (True, 2)
        assert (
            conn.execute(
                "SELECT version,granted_at,revoked_at,approval_kind FROM app.dataset_grants WHERE user_id=%s AND dataset_key='operator-preserved'",
                (owner,),
            ).fetchone()
            == operator
        )


def test_google_only_account_cannot_unlink_last_usable_method(identity_security):
    secure = identity_security
    client, owner = secure.client(linked=False)
    with secure.world.storage.transaction() as conn:
        identity = str(
            conn.execute(
                "SELECT id FROM app.external_identities WHERE user_id=%s", (owner,)
            ).fetchone()[0]
        )
    proof = secure.google_proof(client, "google_unlink", identity)
    before = account_state(secure, owner)
    response = client.post(
        PATH + "/methods/google/" + identity + "/revocations",
        json={"proof_token": proof},
    )
    assert (
        response.status_code == 409
        and response.json()["error"]["code"] == "last_method"
    )
    assert (
        account_state(secure, owner) == before and client.get(PATH).status_code == 200
    )
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT consumed_at IS NULL FROM app.account_action_proofs WHERE secret_digest=%s",
            (token_digest(proof),),
        ).fetchone() == (True,)


def test_unlink_revokes_derived_grant_all_cookies_and_method_revision_atomically(
    identity_security,
):
    secure = identity_security
    client, owner = secure.client()
    copied, _ = secure.client()
    _, foreign = secure.client("B")
    before_foreign = account_state(secure, foreign)
    with secure.world.storage.transaction() as conn:
        identity = str(
            conn.execute(
                "SELECT id FROM app.external_identities WHERE user_id=%s", (owner,)
            ).fetchone()[0]
        )
        conn.execute(
            "INSERT INTO app.dataset_grants(user_id,dataset_key,approval_kind,approval_identity_id,approval_evidence) VALUES(%s,'derived','google_subject',%s,'workspace-A')",
            (owner, identity),
        )
    proof = secure.password_proof(client, "google_unlink", identity)
    assert (
        client.post(
            PATH + "/methods/google/" + identity + "/revocations",
            json={"proof_token": proof},
        ).status_code
        == 200
    )
    assert client.get(PATH).status_code == 401 and copied.get(PATH).status_code == 401
    assert account_state(secure, foreign) == before_foreign
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT is_active,revision FROM app.external_identities WHERE id=%s",
            (identity,),
        ).fetchone() == (False, 2)
        assert conn.execute(
            "SELECT revoked_at IS NOT NULL,version FROM app.dataset_grants WHERE user_id=%s",
            (owner,),
        ).fetchone() == (True, 2)
        assert conn.execute("SELECT purpose FROM app.account_mail").fetchall() == [
            ("google_unlinked",)
        ]


def test_two_accounts_linking_same_subject_have_one_winner_across_pools(
    identity_security,
):
    secure = identity_security
    clients = [secure.client(label)[0] for label in ["A", "B"]]
    inputs = []
    pools = []
    for client in clients:
        proof = secure.password_proof(client, "google_link")
        candidate = secure.candidate(client, proof, subject="concurrent-new-google")
        pool = Storage(
            replace(secure.world.storage.settings, max_waiting=2, wait_seconds=2)
        )
        pools.append(pool)
        passwords = PasswordStore(
            pool,
            secure.passwords.auth_policy,
            secure.passwords.policy,
            secure.passwords.mail_policy,
            hasher=secure.hasher,
        )
        inputs.append(
            (
                GoogleMethods(passwords, secure.world.settings),
                secure.principal(client),
                token_digest(proof),
                token_digest(candidate),
                token_digest(
                    client.cookies.get(identity_cookie(secure.world.settings))
                ),
            )
        )
    barrier = Barrier(2)

    def link(values):
        barrier.wait(timeout=4)
        try:
            return values[0].link(*values[1:])
        except WorkspaceError as error:
            return error.status

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(link, inputs))
        assert (
            sum(isinstance(result, dict) for result in results) == 1
            and results.count(409) == 1
        )
        with secure.world.storage.transaction() as conn:
            assert conn.execute(
                "SELECT count(*) FROM app.external_identities WHERE subject='concurrent-new-google'"
            ).fetchone() == (1,)
    finally:
        for pool in pools:
            pool.close()


@pytest.mark.parametrize("failure", ["notice", "grant_excess"])
def test_unlink_failure_rolls_back_proof_identity_epoch_and_notice(
    identity_security, monkeypatch, failure
):
    secure = identity_security
    client, owner = secure.client()
    with secure.world.storage.transaction() as conn:
        identity = str(
            conn.execute(
                "SELECT id FROM app.external_identities WHERE user_id=%s", (owner,)
            ).fetchone()[0]
        )
        if failure == "grant_excess":
            conn.execute(
                "INSERT INTO app.dataset_grants(user_id,dataset_key,approval_kind,approval_identity_id,approval_evidence) SELECT %s,'derived-'||n,'google_subject',%s,'workspace-A' FROM generate_series(1,21)n",
                (owner, identity),
            )
    proof = secure.password_proof(client, "google_unlink", identity)
    before = account_state(secure, owner)
    if failure == "notice":
        import account.google_methods as module
        from auth.mailconfig import MailUnavailable

        def fail(*args, **kwargs):
            raise MailUnavailable("synthetic")

        monkeypatch.setattr(module, "enqueue", fail)
    assert (
        client.post(
            PATH + "/methods/google/" + identity + "/revocations",
            json={"proof_token": proof},
        ).status_code
        == 503
    )
    assert account_state(secure, owner) == before
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT consumed_at IS NULL FROM app.account_action_proofs WHERE secret_digest=%s",
            (token_digest(proof),),
        ).fetchone() == (True,)
        assert conn.execute("SELECT count(*) FROM app.account_mail").fetchone() == (0,)
