"""Independent pools preserve one-use identity authority and bounded hash work."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Event
import time
from uuid import UUID

import pytest

from account.google_methods import GoogleMethods
from account.google_reauth import GoogleRecentAuth
from account.identity_contracts import PasswordEnrollment
from account.mail_actions import MailActions
from account.security_http import binding_cookie, identity_cookie
from auth.passwords import PasswordStore
from auth.mailoutbox import enqueue, ensure_capacity
from auth.password_limits import digest_key
from auth.password_records import EmailTicket, create_verified_account
from auth.sessions import new_token, token_digest
from storage.pool import Storage
from workspace.errors import WorkspaceError
from security_action_fixtures import PATH
from test_identity_mail_actions import start_email, start_password
from test_identity_methods import account_state


def stores(secure):
    pools = [
        Storage(replace(secure.world.storage.settings, max_waiting=2, wait_seconds=2))
        for _ in range(2)
    ]
    return pools, [
        PasswordStore(
            pool,
            secure.passwords.auth_policy,
            secure.passwords.policy,
            secure.passwords.mail_policy,
            hasher=secure.hasher,
        )
        for pool in pools
    ]


def outcome(work):
    try:
        work()
        return 200
    except WorkspaceError as error:
        return error.status


def test_parallel_google_claims_commit_both_admissions_but_verify_once(
    identity_security,
):
    secure = identity_security
    client, owner = secure.client(linked=False)
    principal = secure.principal(client)
    start = secure.google_start(client)
    credential = secure.assertion(start["nonce"])
    binding = client.cookies.get(binding_cookie(secure.world.settings))
    pools, passwords = stores(secure)
    barrier = Barrier(2)

    def verify(store):
        barrier.wait(timeout=4)
        return outcome(
            lambda: GoogleRecentAuth(store, secure.world.settings).verify(
                principal,
                "password_add",
                "a@gmail.com",
                start["challenge_id"],
                start["challenge_token"],
                binding,
                credential,
            )
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(verify, passwords))
        assert sorted(results) == [200, 403] and len(secure.provider_calls) == 1
        with secure.world.storage.transaction() as conn:
            assert conn.execute(
                "SELECT count(*) FROM app.account_action_proofs WHERE user_id=%s",
                (owner,),
            ).fetchone() == (1,)
            assert conn.execute(
                "SELECT hits FROM app.auth_admission WHERE scope='action:account'"
            ).fetchone() == (3,)
    finally:
        for pool in pools:
            pool.close()


def test_parallel_first_password_hashes_have_one_commit_notice_and_no_foreign_change(
    identity_security,
):
    secure = identity_security
    client, owner = secure.client(linked=False)
    _, foreign = secure.client("B", linked=False)
    foreign_before = account_state(secure, foreign)
    secure.passwords.auth_policy = replace(
        secure.passwords.auth_policy, action_account_limit=5, action_global_limit=30
    )
    body = PasswordEnrollment.model_validate(start_password(secure, client))
    principal = secure.principal(client)
    binding = token_digest(client.cookies.get(identity_cookie(secure.world.settings)))
    pools, passwords = stores(secure)
    entered, release = Barrier(3), Event()

    def hold():
        entered.wait(timeout=4)
        assert release.wait(timeout=5)

    secure.hasher.on_hash = hold

    def change(store):
        return outcome(
            lambda: MailActions(store).add_password(principal, body, binding)
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            futures = [workers.submit(change, store) for store in passwords]
            try:
                entered.wait(timeout=4)
            finally:
                release.set()
            results = [future.result(timeout=6) for future in futures]
        assert results.count(200) == 1 and all(
            status in {200, 401, 403, 409} for status in results
        )
        assert (
            secure.hasher.calls == ["hash", "hash"]
            and account_state(secure, foreign) == foreign_before
        )
        with secure.world.storage.transaction() as conn:
            assert conn.execute(
                "SELECT count(*) FROM app.password_credentials WHERE user_id=%s",
                (owner,),
            ).fetchone() == (1,)
            assert conn.execute(
                "SELECT count(*) FROM app.account_mail WHERE purpose='password_added'"
            ).fetchone() == (1,)
            assert conn.execute(
                "SELECT auth_epoch FROM app.users WHERE id=%s", (owner,)
            ).fetchone() == (1,)
            assert conn.execute(
                "SELECT hits FROM app.auth_admission WHERE scope='action:account'"
            ).fetchone() == (5,)
            assert conn.execute(
                "SELECT count(*) FROM app.password_hash_slots"
            ).fetchone() == (0,)
    finally:
        for pool in pools:
            pool.close()


def test_expired_mail_request_cleanup_and_new_intents_share_mail_before_user_lock(
    identity_security,
):
    secure = identity_security
    client, owner = secure.client()
    email_client, email_owner = secure.client("B")
    expired_client, expired_owner = secure.client("C")
    expired = start_email(secure, expired_client)
    with secure.world.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.account_security_requests SET created_at=now()-interval '30 minutes',expires_at=now()-interval '1 second' WHERE id=%s",
            (expired["request_id"],),
        )
    link_proof = secure.password_proof(client, "google_link")
    email_proof = secure.password_proof(
        email_client, "email_change", "another-primary@example.invalid"
    )
    principal = secure.principal(client)
    email_principal = secure.principal(email_client)
    pools, passwords = stores(secure)
    barrier = Barrier(2)

    def start(pair):
        index, store = pair
        barrier.wait(timeout=4)
        if index == 0:
            return GoogleMethods(store, secure.world.settings).start(
                principal, token_digest(link_proof), new_token(), new_token()
            )
        return MailActions(store).start(
            email_principal,
            "email_change",
            token_digest(email_proof),
            token_digest(new_token()),
            token_digest(new_token()),
            "another-primary@example.invalid",
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(start, enumerate(passwords)))
        assert all(result["schemaVersion"] == 1 for result in results)
        with secure.world.storage.transaction() as conn:
            assert conn.execute(
                "SELECT count(*) FROM app.account_security_requests WHERE id=%s",
                (expired["request_id"],),
            ).fetchone() == (0,)
            assert conn.execute(
                "SELECT user_id,count(*) FROM app.account_security_requests WHERE user_id=ANY(%s) GROUP BY user_id ORDER BY user_id",
                ([owner, email_owner],),
            ).fetchall() == sorted([(UUID(owner), 1), (UUID(email_owner), 1)])
            assert conn.execute(
                "SELECT count(*) FROM app.account_security_requests WHERE user_id=%s",
                (expired_owner,),
            ).fetchone() == (0,)
            assert conn.execute(
                "SELECT auth_epoch FROM app.users WHERE id=ANY(%s) ORDER BY id",
                ([owner, email_owner, expired_owner],),
            ).fetchall() == [(0,), (0,), (0,)]
    finally:
        for pool in pools:
            pool.close()


def test_parallel_unlinks_of_two_final_google_methods_keep_one_usable_method(
    identity_security,
):
    secure = identity_security
    client, owner = secure.client(linked=False)
    with secure.world.storage.transaction() as conn:
        conn.execute(
            "INSERT INTO app.external_identities(user_id,provider,issuer,subject,observed_email_key) VALUES(%s,'google','https://accounts.google.com','second-google-method','second@example.invalid')",
            (owner,),
        )
        identities = [
            str(row[0])
            for row in conn.execute(
                "SELECT id FROM app.external_identities WHERE user_id=%s ORDER BY id",
                (owner,),
            ).fetchall()
        ]
    proofs = [
        secure.google_proof(client, "google_unlink", identity)
        for identity in identities
    ]
    principal = secure.principal(client)
    pools, passwords = stores(secure)
    barrier = Barrier(2)

    def unlink(values):
        store, identity, proof = values
        barrier.wait(timeout=4)
        return outcome(
            lambda: GoogleMethods(store, secure.world.settings).unlink(
                principal, identity, token_digest(proof)
            )
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(
                workers.map(unlink, zip(passwords, identities, proofs, strict=True))
            )
        assert results.count(200) == 1 and all(
            status in {200, 401, 403, 409} for status in results
        )
        with secure.world.storage.transaction() as conn:
            assert conn.execute(
                "SELECT count(*) FROM app.external_identities WHERE user_id=%s AND is_active",
                (owner,),
            ).fetchone() == (1,)
            assert conn.execute(
                "SELECT count(*) FROM app.password_credentials WHERE user_id=%s",
                (owner,),
            ).fetchone() == (0,)
            assert conn.execute(
                "SELECT count(*) FROM app.account_mail WHERE purpose='google_unlinked'"
            ).fetchone() == (1,)
    finally:
        for pool in pools:
            pool.close()


@pytest.mark.parametrize(
    "intent", ["pending_link_without_child", "consumed_expired_mail"]
)
def test_retained_identity_intent_cannot_block_new_login_or_revive_old_session(
    identity_security, intent
):
    secure = identity_security
    client, owner = secure.client()
    principal = secure.principal(client)
    if intent == "pending_link_without_child":
        proof = secure.password_proof(client, "google_link")
        candidate = secure.candidate(
            client, proof, subject="pending-expired-session-google"
        )
        path, method, body = (
            "/google-links",
            "post",
            {"proof_token": proof, "candidate_token": candidate},
        )
        with secure.world.storage.transaction() as conn:
            request_id = str(
                conn.execute(
                    "SELECT id FROM app.account_security_requests WHERE user_id=%s",
                    (owner,),
                ).fetchone()[0]
            )
    else:
        body = start_email(secure, client)
        request_id = body["request_id"]
        path, method = "/email", "put"
        with secure.world.storage.transaction() as conn:
            conn.execute(
                "UPDATE app.account_security_requests SET consumed_at=now(),created_at=now()-interval '30 minutes',expires_at=now()-interval '1 second' WHERE id=%s",
                (request_id,),
            )
    binding = client.cookies.get(identity_cookie(secure.world.settings))
    with secure.world.storage.transaction() as conn:
        sid = conn.execute(
            "SELECT id FROM app.sessions WHERE token_digest=%s",
            (principal.token_digest,),
        ).fetchone()[0]
        conn.execute(
            "UPDATE app.auth_challenges SET created_at=now()-interval '5 minutes',expires_at=now()-interval '1 second' WHERE session_id=%s",
            (sid,),
        )
        conn.execute(
            "UPDATE app.sessions SET created_at=now()-interval '2 hours',idle_expires_at=now()-interval '2 seconds',absolute_expires_at=now()-interval '1 second' WHERE id=%s",
            (sid,),
        )
        if intent == "consumed_expired_mail":
            conn.execute(
                "UPDATE app.account_mail SET created_at=now()-interval '5 minutes',expires_at=now()-interval '1 second'"
            )
            ensure_capacity(conn, secure.passwords.mail_policy, "email_changed")
        retained = conn.execute(
            "SELECT id,operation,consumed_at,verified_at,secret_digest,binding_digest FROM app.account_security_requests WHERE id=%s",
            (request_id,),
        ).fetchone()
    fresh, fresh_owner = secure.client()
    assert fresh_owner == owner and fresh.get(PATH).status_code == 200
    fresh.cookies.set(
        identity_cookie(secure.world.settings),
        binding,
        domain="workspace.fixture",
        path="/",
    )
    assert getattr(fresh, method)(PATH + path, json=body).status_code == 403
    assert client.get(PATH).status_code == 401
    with secure.world.storage.transaction() as conn:
        assert (
            conn.execute(
                "SELECT id,operation,consumed_at,verified_at,secret_digest,binding_digest FROM app.account_security_requests WHERE id=%s",
                (request_id,),
            ).fetchone()
            == retained
        )
        assert conn.execute(
            "SELECT count(*) FROM app.sessions WHERE id=%s", (sid,)
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT count(*) FROM app.auth_challenges WHERE session_id=%s", (sid,)
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM app.external_identities WHERE user_id=%s", (owner,)
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT email_key FROM app.user_emails WHERE user_id=%s AND is_primary",
            (owner,),
        ).fetchone() == ("a@gmail.com",)


def test_registration_takes_mail_before_address_while_email_change_purges_history(
    identity_security,
):
    secure = identity_security
    _, existing_owner = secure.client()
    before = account_state(secure, existing_owner)
    email = "registration-order@example.invalid"
    with secure.world.storage.transaction() as conn:
        first = conn.execute(
            "INSERT INTO app.auth_challenges(purpose,secret_digest,target_email_key,expires_at) VALUES('verify_email',%s,%s,now()+interval '30 minutes') RETURNING id,expires_at",
            (token_digest("h" * 43), email),
        ).fetchone()
        enqueue(
            conn,
            recipient=email,
            purpose="verify_email",
            token="h" * 43,
            expires_at=first[1],
            policy=secure.passwords.mail_policy,
            challenge_id=first[0],
        )
    with secure.world.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.auth_challenges SET created_at=now()-interval '5 minutes',expires_at=now()-interval '1 second' WHERE id=%s",
            (first[0],),
        )
        conn.execute(
            "UPDATE app.account_mail SET created_at=now()-interval '5 minutes',expires_at=now()-interval '1 second' WHERE challenge_id=%s",
            (first[0],),
        )
        # Simulate the existing cooldown elapsing; retain the first spent issue.
        conn.execute(
            "UPDATE app.mail_recipient_budget SET last_queued_at=now()-interval '6 minutes'"
        )
        second = conn.execute(
            "INSERT INTO app.auth_challenges(purpose,secret_digest,target_email_key,expires_at) VALUES('verify_email',%s,%s,now()+interval '30 minutes') RETURNING id,expires_at",
            (token_digest("j" * 43), email),
        ).fetchone()
        enqueue(
            conn,
            recipient=email,
            purpose="verify_email",
            token="j" * 43,
            expires_at=second[1],
            policy=secure.passwords.mail_policy,
            challenge_id=second[0],
        )
        assert conn.execute(
            "SELECT cardinality(issued_at) FROM app.mail_recipient_budget"
        ).fetchone() == (2,)
    ticket = EmailTicket(str(second[0]), "verify_email", email, None, None)
    pools, _ = stores(secure)
    entered = Event()
    backend = []

    def register():
        with pools[1].transaction() as conn:
            backend.append(conn.execute("SELECT pg_backend_pid()").fetchone()[0])
            entered.set()
            return create_verified_account(
                conn,
                ticket,
                secure.hasher.encoded("Synthetic registration password 94"),
                1,
            )

    try:
        with ThreadPoolExecutor(max_workers=1) as worker:
            with pools[0].transaction() as conn:
                # Same mail -> address order as the C final email mutation.
                ensure_capacity(
                    conn, secure.passwords.mail_policy, "email_changed", count=2
                )
                holder = conn.execute("SELECT pg_backend_pid()").fetchone()[0]
                future = worker.submit(register)
                assert entered.wait(timeout=1)
                until = time.monotonic() + 0.6
                while not conn.execute(
                    "SELECT %s=ANY(pg_blocking_pids(%s))", (holder, backend[0])
                ).fetchone()[0]:
                    assert (
                        time.monotonic() < until
                    ), "registration did not reach the held lock"
                    time.sleep(0.005)
                address_lock = int.from_bytes(digest_key(email)[:8], "big", signed=True)
                assert conn.execute(
                    "SELECT pg_try_advisory_xact_lock(%s)", (address_lock,)
                ).fetchone() == (
                    True,
                ), "registration took address before shared mail lock"
            registered = future.result(timeout=3)
        assert (
            registered != existing_owner
            and account_state(secure, existing_owner) == before
        )
        with secure.world.storage.transaction() as conn:
            assert (
                str(
                    conn.execute(
                        "SELECT user_id FROM app.user_emails WHERE email_key=%s",
                        (email,),
                    ).fetchone()[0]
                )
                == registered
            )
            assert conn.execute(
                "SELECT count(*) FROM app.account_mail WHERE challenge_id=ANY(%s)",
                ([first[0], second[0]],),
            ).fetchone() == (0,)
            assert conn.execute(
                "SELECT count(*) FROM app.account_security_requests"
            ).fetchone() == (0,)
    finally:
        for pool in pools:
            pool.close()
