"""Recipient anti-spam state persists independently of bearer/job retention."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta

import pytest

from auth.config import AuthDenied
from auth.mailconfig import MailUnavailable
from auth.mailoutbox import enqueue
from auth.mailqueue import MailOutbox
from storage.pool import Storage
from password_core_helpers import (
    EMAIL,
    MAIL,
    PASSWORD,
    NEW_PASSWORD,
    email_token,
    messages,
    register,
    service,
)


def _later_after_delivery(storage):
    with storage.transaction() as conn:
        # Simulate completed delivery cleanup and six minutes of fixture time.
        conn.execute("DELETE FROM app.account_mail")
        conn.execute(
            "UPDATE app.mail_recipient_budget SET last_queued_at=last_queued_at-interval '6 minutes',issued_at=ARRAY(SELECT stamp-interval '6 minutes' FROM unnest(issued_at) stamp)"
        )


def test_repeated_requests_coalesce_without_invalidating_original_mailbox_proof(
    storage,
):
    store = service(storage)
    store.request_email(EMAIL, "verify_email", "first-peer")
    original = email_token(storage, "verify_email")
    for index in range(12):
        store.request_email(EMAIL, "verify_email", f"peer-{index}")
    assert email_token(storage, "verify_email") == original
    with storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.account_mail").fetchone() == (1,)
        assert conn.execute(
            "SELECT count(*) FROM app.auth_challenges WHERE purpose='verify_email'"
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT cardinality(issued_at) FROM app.mail_recipient_budget"
        ).fetchone() == (1,)
    assert store.complete_verification(original, PASSWORD, "mailbox-owner")


def test_rolling_recipient_limit_survives_deleted_jobs_challenges_and_store_restart(
    storage,
):
    store = service(storage)
    for _ in range(3):
        store.request_email(EMAIL, "verify_email", "fixture")
        assert len(messages(storage, "verify_email")) == 1
        _later_after_delivery(storage)
    with storage.transaction() as conn:
        conn.execute("DELETE FROM app.auth_challenges WHERE purpose='verify_email'")
    service(storage).request_email(EMAIL, "verify_email", "new-peer")
    with storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.account_mail").fetchone() == (0,)
        assert conn.execute(
            "SELECT cardinality(issued_at) FROM app.mail_recipient_budget"
        ).fetchone() == (3,)
    # Only the oldest timestamp crosses 24h. The other two remain enforced.
    with storage.transaction() as conn:
        conn.execute(
            "UPDATE app.mail_recipient_budget SET issued_at=ARRAY[clock_timestamp()-interval '24 hours'+interval '1 minute',clock_timestamp()-interval '1 hour',clock_timestamp()-interval '6 minutes'],last_queued_at=clock_timestamp()-interval '6 minutes'"
        )
    service(storage).request_email(EMAIL, "verify_email", "before-boundary")
    assert messages(storage, "verify_email") == []
    with storage.transaction() as conn:
        conn.execute(
            "UPDATE app.mail_recipient_budget SET issued_at[1]=clock_timestamp()-interval '24 hours 1 second'"
        )
    service(storage).request_email(EMAIL, "verify_email", "after-boundary")
    assert len(messages(storage, "verify_email")) == 1
    with storage.transaction() as conn:
        assert conn.execute(
            "SELECT cardinality(issued_at) FROM app.mail_recipient_budget"
        ).fetchone() == (3,)


def test_five_minute_cooldown_is_independent_of_token_expiry_and_delivery_cleanup(
    storage,
):
    store = service(storage)
    store.request_email(EMAIL, "verify_email", "fixture")
    original = email_token(storage, "verify_email")
    with storage.transaction() as conn:
        conn.execute("DELETE FROM app.account_mail")
        conn.execute(
            "UPDATE app.mail_recipient_budget SET last_queued_at=clock_timestamp()-interval '299 seconds'"
        )
    store.request_email(EMAIL, "verify_email", "before-cooldown")
    assert messages(storage, "verify_email") == []
    with storage.transaction() as conn:
        conn.execute(
            "UPDATE app.mail_recipient_budget SET last_queued_at=clock_timestamp()-interval '301 seconds'"
        )
    store.request_email(EMAIL, "verify_email", "after-cooldown")
    assert len(messages(storage, "verify_email")) == 1
    replacement = email_token(storage, "verify_email")
    assert replacement != original
    assert store.complete_verification(original, PASSWORD, "mailbox-owner")
    with pytest.raises(AuthDenied):
        store.complete_verification(replacement, NEW_PASSWORD, "replay")


def test_verification_quota_cannot_spend_reset_or_completed_reset_notice_allowance(
    storage,
):
    store = service(storage)
    register(store)
    with storage.transaction() as conn:
        conn.execute(
            "UPDATE app.mail_recipient_budget SET issued_at=ARRAY[clock_timestamp()-interval '12 minutes',clock_timestamp()-interval '6 minutes',clock_timestamp()]"
        )
    store.request_email(EMAIL, "password_reset", "fixture")
    proof = email_token(storage, "reset_password")
    with pytest.raises(AuthDenied):
        store.reset_password("X" * 43, NEW_PASSWORD, "attacker")
    assert messages(storage, "password_changed") == []
    store.reset_password(proof, NEW_PASSWORD, "mailbox-owner")
    assert len(messages(storage, "password_changed")) == 1
    with storage.transaction() as conn:
        assert conn.execute(
            "SELECT purpose,cardinality(issued_at) FROM app.mail_recipient_budget ORDER BY purpose"
        ).fetchall() == [("reset_password", 1), ("verify_email", 3)]


def test_two_workers_and_rotating_peers_queue_one_logical_mail(storage):
    shared = Storage(
        replace(storage.settings, max_connections=2, max_waiting=4, wait_seconds=2)
    )
    try:
        shared.readiness()
        stores = [service(shared), service(shared)]
        with ThreadPoolExecutor(max_workers=2) as workers:
            assert list(
                workers.map(
                    lambda i: stores[i].request_email(
                        EMAIL, "verify_email", f"peer-{i}"
                    ),
                    range(2),
                )
            ) == [None, None]
        with storage.transaction() as conn:
            assert conn.execute("SELECT count(*) FROM app.account_mail").fetchone() == (
                1,
            )
            assert conn.execute(
                "SELECT cardinality(issued_at) FROM app.mail_recipient_budget"
            ).fetchone() == (1,)
    finally:
        shared.close()


def test_recipient_ledger_has_hard_cardinality_no_live_eviction_and_expiry_recovery(
    storage,
):
    with storage.transaction() as conn:
        conn.execute(
            "INSERT INTO app.mail_recipient_budget(purpose,recipient_digest,issued_at,last_queued_at,expires_at) SELECT 'verify_email',decode(md5(n::text)||md5('tail'||n::text),'hex'),ARRAY[now()],now(),now()+interval '24 hours' FROM generate_series(1,4096) n"
        )
    store = service(storage)
    store.request_email(EMAIL, "verify_email", "fixture")
    assert messages(storage, "verify_email") == []
    with storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.mail_recipient_budget"
        ).fetchone() == (4096,)
        conn.execute(
            "UPDATE app.mail_recipient_budget SET expires_at=now()-interval '1 second' WHERE recipient_digest=decode(md5('1')||md5('tail1'),'hex')"
        )
    store.request_email(EMAIL, "verify_email", "fixture")
    assert len(messages(storage, "verify_email")) == 1
    with storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.mail_recipient_budget"
        ).fetchone() == (4096,)


@pytest.mark.parametrize(
    "change", ["recipient", "purpose", "token", "expiry", "consumed"]
)
def test_enqueue_rejects_mismatched_challenge_before_recipient_reservation(
    storage, change
):
    store = service(storage)
    store.request_email(EMAIL, "verify_email", "fixture")
    token = email_token(storage, "verify_email")
    with storage.transaction() as conn:
        ticket, expiry = conn.execute(
            "SELECT id,expires_at FROM app.auth_challenges WHERE purpose='verify_email'"
        ).fetchone()
        recipient = EMAIL
        purpose = "verify_email"
        if change == "recipient":
            recipient = "different@example.invalid"
        elif change == "purpose":
            purpose = "reset_password"
        elif change == "token":
            token = "X" * 43
        elif change == "expiry":
            expiry -= timedelta(seconds=1)
        else:
            conn.execute(
                "UPDATE app.auth_challenges SET consumed_at=clock_timestamp() WHERE id=%s",
                (ticket,),
            )
        with pytest.raises(MailUnavailable, match="account_mail_challenge_invalid"):
            enqueue(
                conn,
                recipient=recipient,
                purpose=purpose,
                token=token,
                expires_at=expiry,
                policy=MAIL,
                challenge_id=ticket,
            )
        assert conn.execute(
            "SELECT cardinality(issued_at) FROM app.mail_recipient_budget"
        ).fetchone() == (1,)


def test_worker_does_not_deliver_retargeted_challenge_or_changed_account_epoch(storage):
    store = service(storage)
    owner, _ = register(store)
    store.request_email(EMAIL, "password_reset", "fixture")
    with storage.transaction() as conn:
        conn.execute(
            "UPDATE app.users SET auth_epoch=auth_epoch+1 WHERE id=%s", (owner,)
        )
    assert MailOutbox(storage, MAIL).claim() is None
    with storage.transaction() as conn:
        conn.execute(
            "UPDATE app.users SET auth_epoch=auth_epoch-1 WHERE id=%s", (owner,)
        )
        conn.execute(
            "UPDATE app.auth_challenges SET target_email_key='different@example.invalid' WHERE purpose='password_reset'"
        )
    assert MailOutbox(storage, MAIL).claim() is None


def test_repeated_public_mail_requests_queue_one_job_before_cooldown(storage):
    """Red selector intentionally depends only on the pre-existing public store API."""
    store = service(storage)
    for index in range(6):
        store.request_email(EMAIL, "verify_email", f"rotated-peer-{index}")
    with storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.account_mail WHERE purpose='verify_email'"
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT count(*) FROM app.auth_challenges WHERE purpose='verify_email'"
        ).fetchone() == (1,)
