"""Captured synthetic mail only: encryption, capacity, fencing and retry recovery."""

from dataclasses import replace
from datetime import timedelta
import hashlib
import uuid
import secrets
import re

import pytest

from auth.mailconfig import MailPolicy, MailUnavailable, load_mail_policy
from auth.mailoutbox import enqueue, ensure_capacity, open_job
from auth.mailqueue import MailOutbox
from auth.mailworker import MailWorker

RECIPIENT = "mail.fixture@example.invalid"
TOKEN = "M" * 43
POLICY = MailPolicy(True, b"K" * 32)


def _enqueue(storage, policy=POLICY, purpose="verify_email", recipient=None):
    recipient = recipient or "mail-" + uuid.uuid4().hex + "@example.invalid"
    mail_token = secrets.token_urlsafe(32)
    with storage.transaction() as conn:
        expiry = conn.execute(
            "SELECT clock_timestamp()+interval '30 minutes'"
        ).fetchone()[0]
        challenge = None
        if purpose != "password_changed":
            owner = None
            if purpose == "reset_password":
                owner = conn.execute(
                    "INSERT INTO app.users(status) VALUES ('active') RETURNING id"
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO app.password_credentials(user_id,encoded_hash,policy_version) VALUES (%s,%s,1)",
                    (owner, "fixture-only-unused-hash" * 3),
                )
                conn.execute(
                    "INSERT INTO app.user_emails(user_id,address,email_key,verified_at,verification_method,is_primary) VALUES (%s,%s,%s,now(),'email',true)",
                    (owner, recipient, recipient),
                )
            challenge = conn.execute(
                "INSERT INTO app.auth_challenges(purpose,secret_digest,expires_at,target_email_key,user_id,password_auth_epoch) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                (
                    "verify_email" if purpose == "verify_email" else "password_reset",
                    hashlib.sha256(mail_token.encode()).digest(),
                    expiry,
                    recipient,
                    owner,
                    0 if owner else None,
                ),
            ).fetchone()[0]
        job_id = enqueue(
            conn,
            recipient=recipient,
            purpose=purpose,
            token=mail_token if challenge else None,
            expires_at=expiry,
            policy=policy,
            challenge_id=challenge,
        )
        return job_id, challenge


def _advance(storage, job_id=None, reclaim=False):
    """Move only synthetic fixture rows; no sleeping or real service work."""
    with storage.transaction() as conn:
        conn.execute(
            "UPDATE app.account_mail_control SET last_attempt_at=clock_timestamp()-interval '2 seconds'"
        )
        if reclaim:
            conn.execute(
                "UPDATE app.account_mail_control SET lease_expires_at=clock_timestamp()-interval '1 second'"
            )
        if job_id:
            conn.execute(
                "UPDATE app.account_mail SET available_at=clock_timestamp()-interval '1 second' WHERE id=%s",
                (job_id,),
            )
            if reclaim:
                conn.execute(
                    "UPDATE app.account_mail SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=%s",
                    (job_id,),
                )


def test_mail_feature_is_off_and_secret_repr_is_redacted_by_default():
    assert not load_mail_policy({}).enabled
    assert "synthetic-outbox" not in repr(POLICY)
    with pytest.raises(MailUnavailable):
        load_mail_policy(
            {"ACCOUNT_MAIL_ENABLED": "true", "ACCOUNT_MAIL_OUTBOX_KEY": "not-a-key"}
        )


@pytest.mark.parametrize(
    "origin",
    [
        "http://aqua-ai.us",
        "https://user@aqua-ai.us",
        "https://aqua-ai.us/x",
        "https://aqua-ai.us/#evil",
    ],
)
def test_mail_origin_cannot_be_user_redirect_or_insecure(origin):
    with pytest.raises(MailUnavailable):
        MailPolicy(True, POLICY.key, origin)


@pytest.mark.parametrize(
    "purpose", ["verify_email", "reset_password", "password_changed"]
)
def test_worker_opens_bound_envelope_no_plaintext_recipient_or_token_in_db(
    storage, purpose
):
    job_id, _ = _enqueue(storage, purpose=purpose, recipient=RECIPIENT)
    outbox = MailOutbox(storage, POLICY)
    job = outbox.claim()
    assert job.id == job_id
    payload = open_job(job, POLICY)
    assert payload["to"] == RECIPIENT
    if purpose == "password_changed":
        assert TOKEN not in payload["text"] and "#token=" not in payload["text"]
    else:
        assert re.search(r"#token=[A-Za-z0-9_-]{43}", payload["text"])
    with storage.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM app.account_mail WHERE id=%s", (job_id,)
        ).fetchone()
        clear_token = re.search(r"#token=([A-Za-z0-9_-]{43})", payload["text"])
        assert (
            clear_token is None or clear_token[1] not in repr(row)
        ) and RECIPIENT not in repr(row)
    assert TOKEN not in repr(job) and RECIPIENT not in repr(job)


@pytest.mark.parametrize(
    "change", ["id", "purpose", "recipient", "expiry", "ciphertext", "key"]
)
def test_swapping_ciphertext_metadata_or_key_never_sends(storage, change):
    _enqueue(storage)
    job = MailOutbox(storage, POLICY).claim()
    policy = POLICY
    if change == "id":
        job = replace(job, id=uuid.uuid4())
    elif change == "purpose":
        job = replace(job, purpose="reset_password")
    elif change == "recipient":
        job = replace(job, recipient_digest=b"x" * 32)
    elif change == "expiry":
        job = replace(job, expires_at=job.expires_at + timedelta(seconds=1))
    elif change == "ciphertext":
        job = replace(
            job, ciphertext=job.ciphertext[:-1] + bytes([job.ciphertext[-1] ^ 1])
        )
    else:
        policy = replace(POLICY, key=b"x" * 32)
    with pytest.raises(MailUnavailable, match="account_mail_envelope_invalid"):
        open_job(job, policy)


def test_transaction_rollback_never_leaves_token_job_without_challenge(storage):
    with pytest.raises(RuntimeError):
        with storage.transaction() as conn:
            expiry = conn.execute(
                "SELECT clock_timestamp()+interval '1 minute'"
            ).fetchone()[0]
            challenge = conn.execute(
                "INSERT INTO app.auth_challenges(purpose,secret_digest,expires_at,target_email_key) VALUES ('verify_email',%s,%s,'mail.fixture@example.invalid') RETURNING id",
                (hashlib.sha256(TOKEN.encode()).digest(), expiry),
            ).fetchone()[0]
            enqueue(
                conn,
                recipient=RECIPIENT,
                purpose="verify_email",
                token=TOKEN,
                expires_at=expiry,
                policy=POLICY,
                challenge_id=challenge,
            )
            raise RuntimeError("fixture_rollback")
    with storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.account_mail").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM app.auth_challenges").fetchone() == (
            0,
        )


def test_capacity_check_before_account_lookup_and_no_live_eviction(storage):
    policy = replace(POLICY, max_pending=1, max_rows=2)
    job_id, _ = _enqueue(storage, policy)
    with pytest.raises(MailUnavailable, match="account_mail_capacity"):
        with storage.transaction() as conn:
            ensure_capacity(conn, policy)
    with storage.transaction() as conn:
        assert conn.execute("SELECT id FROM app.account_mail").fetchall() == [(job_id,)]


def test_consumed_or_expired_challenge_not_delivered(storage):
    job_id, challenge = _enqueue(storage)
    with storage.transaction() as conn:
        conn.execute(
            "UPDATE app.auth_challenges SET consumed_at=clock_timestamp() WHERE id=%s",
            (challenge,),
        )
    assert MailOutbox(storage, POLICY).claim() is None
    with storage.transaction() as conn:
        conn.execute(
            "UPDATE app.account_mail SET created_at=clock_timestamp()-interval '1 hour',expires_at=clock_timestamp()-interval '1 second' WHERE id=%s",
            (job_id,),
        )
    assert MailOutbox(storage, POLICY).claim() is None
    with storage.transaction() as conn:
        assert conn.execute("SELECT state FROM app.account_mail").fetchone() == (
            "expired",
        )


def test_unknown_acceptance_retries_same_job_and_body_with_three_attempt_cap(storage):
    job_id, _ = _enqueue(storage)
    box = MailOutbox(storage, POLICY)
    bodies = []
    for attempt in range(1, 4):
        _advance(storage, job_id)
        job = box.claim()
        assert job.id == job_id and job.attempts == attempt
        bodies.append(open_job(job, POLICY))
        assert box.finish(job, "retry")
    assert bodies[0] == bodies[1] == bodies[2]
    _advance(storage, job_id)
    assert box.claim() is None
    with storage.transaction() as conn:
        assert conn.execute(
            "SELECT state,attempts FROM app.account_mail"
        ).fetchone() == ("failed", 3)


def test_global_lease_and_stale_worker_fence_recovers_after_crash(storage):
    job_id, _ = _enqueue(storage)
    box = MailOutbox(storage, POLICY)
    old = box.claim()
    assert box.claim() is None
    _advance(storage, job_id, reclaim=True)
    fresh = box.claim()
    assert fresh.id == old.id and fresh.lease_id != old.lease_id
    assert not box.finish(old, "accepted")
    assert box.finish(fresh, "accepted")
    with storage.transaction() as conn:
        assert conn.execute(
            "SELECT state,attempts FROM app.account_mail"
        ).fetchone() == ("sent", 2)


@pytest.mark.parametrize("budget", ["hour_hits=20", "day_hits=60"])
def test_persisted_delivery_budgets_deny_before_transport_and_recover(storage, budget):
    _enqueue(storage)
    with storage.transaction() as conn:
        conn.execute("UPDATE app.account_mail_control SET " + budget)
    calls = []

    class Fake:
        def send(self, *args):
            calls.append(args)
            return "accepted"

    worker = MailWorker(MailOutbox(storage, POLICY), Fake())
    assert worker.once() is False and not calls
    with storage.transaction() as conn:
        conn.execute(
            "UPDATE app.account_mail_control SET hour_started_at=clock_timestamp()-interval '2 hours',day_started_at=clock_timestamp()-interval '2 days'"
        )
    assert worker.once() is True and len(calls) == 1


def test_worker_logs_fixed_outcome_only_and_no_plaintext_or_transport_on_tamper(
    storage, caplog
):
    _enqueue(storage)
    with storage.transaction() as conn:
        conn.execute(
            "UPDATE app.account_mail SET ciphertext=decode(repeat('00',40),'hex')"
        )

    class Never:
        def send(self, *args):
            raise AssertionError("tampered mail reached provider")

    with caplog.at_level("INFO", logger="aqua.account_mail"):
        assert MailWorker(MailOutbox(storage, POLICY), Never()).once()
    assert "reason=invalid" in caplog.text
    assert TOKEN not in caplog.text and RECIPIENT not in caplog.text


@pytest.mark.parametrize(
    "recipient",
    ["bad\r\nBcc: victim@example.invalid", "bad\n@example.invalid", "no-at-sign"],
)
def test_mail_header_injection_rejected_before_insert(storage, recipient):
    with storage.transaction() as conn:
        expiry = conn.execute(
            "SELECT clock_timestamp()+interval '1 minute'"
        ).fetchone()[0]
        with pytest.raises(MailUnavailable):
            enqueue(
                conn,
                recipient=recipient,
                purpose="password_changed",
                token=None,
                expires_at=expiry,
                policy=POLICY,
            )


def test_delivery_second_budget_survives_worker_restart(storage):
    first, _ = _enqueue(storage)
    second, _ = _enqueue(storage)
    box = MailOutbox(storage, POLICY)
    job = box.claim()
    assert box.finish(job, "accepted")
    assert MailOutbox(storage, POLICY).claim() is None
    _advance(storage)
    next_job = MailOutbox(storage, POLICY).claim()
    assert {job.id, next_job.id} == {first, second}


def test_parallel_workers_share_one_persisted_inflight_lease(storage):
    from concurrent.futures import ThreadPoolExecutor
    from storage.pool import Storage

    _enqueue(storage)
    _enqueue(storage)
    shared = Storage(
        replace(storage.settings, max_connections=2, max_waiting=4, wait_seconds=2)
    )
    try:
        shared.readiness()
        boxes = [MailOutbox(shared, POLICY), MailOutbox(shared, POLICY)]
        with ThreadPoolExecutor(max_workers=2) as threads:
            claimed = list(threads.map(lambda index: boxes[index].claim(), range(2)))
        assert sum(item is not None for item in claimed) == 1
        with storage.transaction() as conn:
            assert conn.execute(
                "SELECT count(*) FROM app.account_mail WHERE state='sending'"
            ).fetchone() == (1,)
    finally:
        shared.close()


def test_unknown_acceptance_never_retried_outside_provider_deduplication_window(
    storage,
):
    job_id, _ = _enqueue(storage)
    box = MailOutbox(storage, POLICY)
    job = box.claim()
    assert box.finish(job, "retry")
    _advance(storage, job_id)
    with storage.transaction() as conn:
        conn.execute(
            "UPDATE app.account_mail SET first_attempt_at=clock_timestamp()-interval '23 hours 1 minute' WHERE id=%s",
            (job_id,),
        )
    assert box.claim() is None


@pytest.mark.parametrize("outcome", ["accepted", "permanent", "invalid"])
def test_terminal_delivery_wipes_encrypted_bearer_immediately(storage, outcome):
    job_id, _ = _enqueue(storage)
    box = MailOutbox(storage, POLICY)
    job = box.claim()
    assert box.finish(job, outcome)
    with storage.transaction() as conn:
        retained = conn.execute(
            "SELECT ciphertext FROM app.account_mail WHERE id=%s", (job_id,)
        ).fetchone()[0]
    assert retained == bytes(30) and retained != job.ciphertext


def test_provider_accepted_then_database_completion_lost_retries_idempotently(
    storage, monkeypatch
):
    from storage.pool import StorageUnavailable

    job_id, _ = _enqueue(storage)
    box = MailOutbox(storage, POLICY)
    delivered = {}
    calls = []

    class Fake:
        def send(self, ident, payload):
            calls.append(ident)
            if ident in delivered:
                assert delivered[ident] == payload
            else:
                delivered[ident] = payload
            return "accepted"

    worker = MailWorker(box, Fake())
    original = box.finish

    def unavailable(*args):
        raise StorageUnavailable("application_storage_unavailable")

    monkeypatch.setattr(box, "finish", unavailable)
    with pytest.raises(StorageUnavailable):
        worker.once()
    monkeypatch.setattr(box, "finish", original)
    _advance(storage, job_id, reclaim=True)
    assert worker.once()
    assert calls == [job_id, job_id] and len(delivered) == 1
    with storage.transaction() as conn:
        assert conn.execute(
            "SELECT state,attempts FROM app.account_mail"
        ).fetchone() == ("sent", 2)


def test_registration_backlog_cannot_delay_password_reset_or_security_notice(storage):
    for _ in range(15):
        _enqueue(storage)
    reset, _ = _enqueue(storage, purpose="reset_password")
    notice, _ = _enqueue(storage, purpose="password_changed")
    box = MailOutbox(storage, POLICY)
    first = box.claim()
    assert first.id == notice and first.purpose == "password_changed"
    assert box.finish(first, "accepted")
    _advance(storage)
    second = box.claim()
    assert second.id == reset and second.purpose == "reset_password"
    assert box.finish(second, "accepted")
    with storage.transaction() as conn:
        assert conn.execute(
            "SELECT verify_hour_hits,verify_day_hits,reset_hour_hits,notice_hour_hits FROM app.account_mail_control"
        ).fetchone() == (0, 0, 1, 1)
        assert conn.execute(
            "SELECT count(*) FROM app.account_mail WHERE purpose='verify_email' AND state='pending'"
        ).fetchone() == (15,)


@pytest.mark.parametrize("dimension", ["hour", "day"])
def test_registration_exhaustion_preserves_recovery_and_notice_allowances(
    storage, dimension
):
    _enqueue(storage)
    with storage.transaction() as conn:
        if dimension == "hour":
            conn.execute(
                "UPDATE app.account_mail_control SET verify_hour_hits=5,hour_hits=5"
            )
        else:
            conn.execute(
                "UPDATE app.account_mail_control SET verify_day_hits=20,day_hits=20"
            )
    assert MailOutbox(storage, POLICY).claim() is None
    reset, _ = _enqueue(storage, purpose="reset_password")
    notice, _ = _enqueue(storage, purpose="password_changed")
    # A different worker/restart still sees the partitioned stored counters.
    first = MailOutbox(storage, POLICY).claim()
    assert first.id == notice
    assert MailOutbox(storage, POLICY).finish(first, "accepted")
    _advance(storage)
    second = MailOutbox(storage, POLICY).claim()
    assert second.id == reset


def test_registration_queue_partition_cannot_consume_recovery_queue_slots(storage):
    seed, _ = _enqueue(storage)
    with storage.transaction() as conn:
        # 1,024 synthetic registration jobs, no real recipient or transport work.
        conn.execute(
            "INSERT INTO app.account_mail(id,purpose,recipient_digest,ciphertext,challenge_id,expires_at) SELECT gen_random_uuid(),m.purpose,m.recipient_digest,m.ciphertext,m.challenge_id,m.expires_at FROM app.account_mail m CROSS JOIN generate_series(1,1023) WHERE m.id=%s",
            (seed,),
        )
    with pytest.raises(MailUnavailable, match="account_mail_capacity"):
        with storage.transaction() as conn:
            ensure_capacity(conn, POLICY, "verify_email")
    reset, _ = _enqueue(storage, purpose="reset_password")
    notice, _ = _enqueue(storage, purpose="password_changed")
    box = MailOutbox(storage, POLICY)
    first = box.claim()
    assert first.id == notice
    assert box.finish(first, "accepted")
    _advance(storage)
    assert box.claim().id == reset


def test_admitted_reset_volume_has_at_least_matching_notice_delivery_capacity(storage):
    for index in range(5):
        address = f"notice-volume-{index}@example.invalid"
        _enqueue(storage, purpose="reset_password", recipient=address)
        _enqueue(storage, purpose="password_changed", recipient=address)
    box = MailOutbox(storage, POLICY)
    purposes = []
    for _ in range(10):
        _advance(storage)
        job = box.claim()
        assert job is not None
        purposes.append(job.purpose)
        assert box.finish(job, "accepted")
    assert purposes == ["password_changed"] * 5 + ["reset_password"] * 5
    with storage.transaction() as conn:
        assert conn.execute(
            "SELECT hour_hits,day_hits,reset_hour_hits,notice_hour_hits FROM app.account_mail_control"
        ).fetchone() == (10, 10, 5, 5)
