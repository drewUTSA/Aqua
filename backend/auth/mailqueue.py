"""One leased account email at a time, with persisted attempt and volume bounds."""

from collections.abc import Sequence
from datetime import datetime
import uuid

from psycopg import Connection

from auth.mailconfig import MailPolicy
from auth.mailoutbox import MailJob
from storage.pool import Storage

# Partitions sum to the global 20/hour and 60/day. Anonymous verification mail
# cannot spend recovery/security allowances, even after a process restart.
PRIORITIES = (
    ("password_changed", 10, 20),
    ("reset_password", 5, 20),
    ("verify_email", 5, 20),
)


def _claimable(
    conn: Connection, instant: datetime, allowed: Sequence[str]
) -> tuple[uuid.UUID, str, bytes, bytes, datetime, int] | None:
    for purpose in allowed:
        row = conn.execute(
            "SELECT m.id,m.purpose,m.recipient_digest,m.ciphertext,m.expires_at,m.attempts "
            "FROM app.account_mail m WHERE m.state IN ('pending','sending') AND m.purpose=%s "
            "AND m.available_at<=%s AND (m.lease_expires_at IS NULL OR m.lease_expires_at<=%s) "
            "AND m.expires_at>%s AND m.attempts<3 "
            "AND (m.first_attempt_at IS NULL OR m.first_attempt_at>%s-interval '23 hours') "
            "AND (m.purpose='password_changed' OR EXISTS (SELECT 1 FROM app.auth_challenges c "
            "WHERE c.id=m.challenge_id AND c.consumed_at IS NULL AND c.expires_at>%s "
            "AND c.expires_at=m.expires_at AND sha256(convert_to(c.target_email_key,'UTF8'))=m.recipient_digest "
            "AND ((m.purpose='verify_email' AND c.purpose='verify_email' AND c.user_id IS NULL) "
            "OR (m.purpose='reset_password' AND c.purpose='password_reset' AND EXISTS "
            "(SELECT 1 FROM app.users u JOIN app.user_emails e ON e.user_id=u.id "
            "JOIN app.password_credentials p ON p.user_id=u.id WHERE u.id=c.user_id "
            "AND u.status='active' AND u.auth_epoch=c.password_auth_epoch "
            "AND e.email_key=c.target_email_key AND e.is_primary AND e.verified_at IS NOT NULL))))) "
            "ORDER BY m.available_at,m.id LIMIT 1 FOR UPDATE OF m SKIP LOCKED",
            (purpose, instant, instant, instant, instant, instant),
        ).fetchone()
        if row is not None:
            return row
    return None


class MailOutbox:
    def __init__(self, storage: Storage, policy: MailPolicy) -> None:
        self.storage, self.policy = storage, policy

    def claim(self) -> MailJob | None:
        if not self.policy.enabled:
            return None
        with self.storage.transaction() as conn:
            control = conn.execute(
                "SELECT last_attempt_at,hour_started_at,hour_hits,day_started_at,day_hits,lease_expires_at "
                ",notice_hour_hits,notice_day_hits,reset_hour_hits,reset_day_hits,verify_hour_hits,verify_day_hits "
                "FROM app.account_mail_control WHERE singleton FOR UPDATE SKIP LOCKED"
            ).fetchone()
            if control is None:
                return None
            instant = conn.execute("SELECT clock_timestamp()").fetchone()[0]
            last, hour, hour_hits, day, day_hits, lease_until = control[:6]
            if lease_until is not None and lease_until > instant:
                return None
            hour_hits = 0 if (instant - hour).total_seconds() >= 3600 else hour_hits
            day_hits = 0 if (instant - day).total_seconds() >= 86400 else day_hits
            purpose_hits = {}
            for index, (purpose, _, _) in enumerate(PRIORITIES):
                hourly, daily = control[6 + index * 2 : 8 + index * 2]
                purpose_hits[purpose] = [
                    0 if (instant - hour).total_seconds() >= 3600 else hourly,
                    0 if (instant - day).total_seconds() >= 86400 else daily,
                ]
            # Index-bounded maintenance; expired links are never delivered.
            conn.execute(
                "UPDATE app.account_mail SET state='expired',ciphertext=decode(repeat('00',30),'hex'),lease_id=NULL,lease_expires_at=NULL WHERE id IN "
                "(SELECT id FROM app.account_mail WHERE state IN ('pending','sending') AND expires_at<=%s "
                "ORDER BY expires_at,id LIMIT %s FOR UPDATE SKIP LOCKED)",
                (instant, self.policy.cleanup_batch),
            )
            conn.execute(
                "UPDATE app.account_mail SET state='failed',ciphertext=decode(repeat('00',30),'hex'),lease_id=NULL,lease_expires_at=NULL WHERE id IN "
                "(SELECT id FROM app.account_mail WHERE state IN ('pending','sending') "
                "AND (lease_expires_at IS NULL OR lease_expires_at<=%s) "
                "AND (attempts>=3 OR first_attempt_at<=%s-interval '23 hours') "
                "ORDER BY available_at,id LIMIT %s FOR UPDATE SKIP LOCKED)",
                (instant, instant, self.policy.cleanup_batch),
            )
            if (
                (instant - last).total_seconds() < 1
                or hour_hits >= 20
                or day_hits >= 60
            ):
                return None
            allowed = [
                purpose
                for purpose, hour_cap, day_cap in PRIORITIES
                if purpose_hits[purpose][0] < hour_cap
                and purpose_hits[purpose][1] < day_cap
            ]
            row = _claimable(conn, instant, allowed)
            if row is None:
                return None
            lease = uuid.uuid4()
            purpose_hits[row[1]][0] += 1
            purpose_hits[row[1]][1] += 1
            conn.execute(
                "UPDATE app.account_mail SET state='sending',attempts=attempts+1,lease_id=%s,"
                "lease_expires_at=%s+interval '90 seconds',first_attempt_at=COALESCE(first_attempt_at,%s) WHERE id=%s",
                (lease, instant, instant, row[0]),
            )
            conn.execute(
                "UPDATE app.account_mail_control SET last_attempt_at=%s,"
                "hour_started_at=CASE WHEN %s-hour_started_at>=interval '1 hour' THEN %s ELSE hour_started_at END,"
                "hour_hits=%s,day_started_at=CASE WHEN %s-day_started_at>=interval '24 hours' THEN %s ELSE day_started_at END,"
                "day_hits=%s,lease_id=%s,lease_expires_at=%s+interval '90 seconds',"
                "notice_hour_hits=%s,notice_day_hits=%s,reset_hour_hits=%s,reset_day_hits=%s,verify_hour_hits=%s,verify_day_hits=%s WHERE singleton",
                (
                    instant,
                    instant,
                    instant,
                    hour_hits + 1,
                    instant,
                    instant,
                    day_hits + 1,
                    lease,
                    instant,
                    *purpose_hits["password_changed"],
                    *purpose_hits["reset_password"],
                    *purpose_hits["verify_email"],
                ),
            )
            return MailJob(*row[:5], lease, row[5] + 1)

    def finish(self, job: MailJob, outcome: str) -> bool:
        """Fence stale workers. Retry only this same UUID/body within its TTL."""
        if outcome not in {"accepted", "retry", "permanent", "invalid"}:
            raise ValueError("account_mail_outcome_invalid")
        state = (
            "sent"
            if outcome == "accepted"
            else "pending" if outcome == "retry" and job.attempts < 3 else "failed"
        )
        with self.storage.transaction() as conn:
            # Claim and finish share control -> job lock order; avoid a reclaimed
            # job racing its old worker into a lock-order deadlock.
            conn.execute(
                "SELECT singleton FROM app.account_mail_control WHERE singleton FOR UPDATE"
            )
            updated = conn.execute(
                "UPDATE app.account_mail SET state=%s,lease_id=NULL,lease_expires_at=NULL,"
                "available_at=clock_timestamp()+%s*interval '1 second',"
                "ciphertext=CASE WHEN %s='pending' THEN ciphertext ELSE decode(repeat('00',30),'hex') END "
                "WHERE id=%s AND state='sending' AND lease_id=%s RETURNING id",
                (state, 30 * (2 ** (job.attempts - 1)), state, job.id, job.lease_id),
            ).fetchone()
            conn.execute(
                "UPDATE app.account_mail_control SET lease_id=NULL,lease_expires_at=NULL "
                "WHERE singleton AND lease_id=%s",
                (job.lease_id,),
            )
            return updated is not None
