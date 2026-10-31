"""New purposes cannot multiply recipient, queue or persisted worker allowances."""

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from auth.mailconfig import MailUnavailable
from auth.mailoutbox import MailJob, enqueue, open_job
from auth.mailqueue import MailOutbox
from auth.mailrecipient import reserve
from security_action_fixtures import PATH
from test_identity_mail_actions import start_email


def test_verification_purpose_rotation_spends_one_recipient_bucket(identity_security):
    secure = identity_security
    recipient = "bounded-recipient@example.invalid"
    with secure.world.storage.transaction() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(1095848261)")
        reserve(conn, recipient, "verify_email")
        conn.execute(
            "UPDATE app.mail_recipient_budget SET last_queued_at=now()-interval '6 minutes'"
        )
        reserve(conn, recipient, "email_change_new")
        conn.execute(
            "UPDATE app.mail_recipient_budget SET last_queued_at=now()-interval '6 minutes'"
        )
        reserve(conn, recipient, "password_add")
        conn.execute(
            "UPDATE app.mail_recipient_budget SET last_queued_at=now()-interval '6 minutes'"
        )
        with pytest.raises(MailUnavailable):
            reserve(conn, recipient, "email_change_old")
        assert conn.execute(
            "SELECT purpose,cardinality(issued_at) FROM app.mail_recipient_budget"
        ).fetchall() == [("verify_email", 3)]


def test_all_mandatory_notice_purposes_share_ten_hourly_attempts(identity_security):
    secure = identity_security
    purposes = [
        "password_changed",
        "password_added",
        "email_changed",
        "google_linked",
        "google_unlinked",
    ]
    with secure.world.storage.transaction() as conn:
        expiry = conn.execute("SELECT clock_timestamp()+interval '1 hour'").fetchone()[
            0
        ]
        for index in range(11):
            enqueue(
                conn,
                recipient="security-notice@example.invalid",
                purpose=purposes[index % 5],
                token=None,
                expires_at=expiry,
                policy=secure.passwords.mail_policy,
            )
    outbox = MailOutbox(secure.world.storage, secure.passwords.mail_policy)
    for _ in range(10):
        with secure.world.storage.transaction() as conn:
            conn.execute(
                "UPDATE app.account_mail_control SET last_attempt_at=now()-interval '2 seconds'"
            )
        job = outbox.claim()
        assert job is not None
        assert open_job(job, secure.passwords.mail_policy)["purpose"] in purposes
        assert outbox.finish(job, "accepted")
    with secure.world.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.account_mail_control SET last_attempt_at=now()-interval '2 seconds'"
        )
    assert outbox.claim() is None
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT hour_hits,notice_hour_hits,notice_day_hits,verify_hour_hits,reset_hour_hits FROM app.account_mail_control"
        ).fetchone() == (10, 10, 10, 0, 0)


def test_new_mail_envelope_cannot_change_purpose_recipient_expiry_or_request(
    identity_security,
):
    secure = identity_security
    client, _ = secure.client()
    body = start_email(secure, client)
    with secure.world.storage.transaction() as conn:
        rows = conn.execute(
            "SELECT m.id,m.purpose,m.recipient_digest,m.ciphertext,m.expires_at FROM app.account_mail m JOIN app.auth_challenges c ON c.id=m.challenge_id WHERE c.account_request_id=%s ORDER BY m.purpose",
            (body["request_id"],),
        ).fetchall()
    job = MailJob(*rows[0], uuid4(), 0)
    payload = open_job(job, secure.passwords.mail_policy)
    assert (
        payload["request_id"] == body["request_id"]
        and "#request=" + body["request_id"] + "&token=" in payload["text"]
    )
    for forged in [
        replace(job, purpose="password_add"),
        replace(job, recipient_digest=b"x" * 32),
        replace(job, expires_at=job.expires_at + timedelta(seconds=1)),
        replace(job, id=uuid4()),
    ]:
        with pytest.raises(MailUnavailable):
            open_job(forged, secure.passwords.mail_policy)


def test_mandatory_notice_survives_request_cleanup_and_primary_switch(
    identity_security,
):
    secure = identity_security
    client, owner = secure.client()
    body = start_email(secure, client)
    assert client.put(PATH + "/email", json=body).status_code == 200
    with secure.world.storage.transaction() as conn:
        rows = conn.execute(
            "SELECT id,purpose,recipient_digest,ciphertext,expires_at FROM app.account_mail WHERE purpose='email_changed' ORDER BY id"
        ).fetchall()
        conn.execute(
            "UPDATE app.account_security_requests SET created_at=now()-interval '30 minutes',expires_at=now()-interval '1 second' WHERE id=%s",
            (body["request_id"],),
        )
    fresh, _ = secure.client()
    proof = secure.password_proof(fresh, "google_link")
    assert (
        fresh.post(
            PATH + "/google-link-challenges", json={"proof_token": proof}
        ).status_code
        == 200
    )
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.account_security_requests WHERE id=%s",
            (body["request_id"],),
        ).fetchone() == (0,)
        assert (
            conn.execute(
                "SELECT id,purpose,recipient_digest,ciphertext,expires_at FROM app.account_mail WHERE purpose='email_changed' ORDER BY id"
            ).fetchall()
            == rows
        )
    outbox = MailOutbox(secure.world.storage, secure.passwords.mail_policy)
    job = outbox.claim()
    assert job.purpose == "email_changed" and open_job(
        job, secure.passwords.mail_policy
    )["to"] in {"a@gmail.com", "new-primary@example.invalid"}
