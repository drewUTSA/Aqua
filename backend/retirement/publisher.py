"""Private host-only publisher primitives; no cron/key/credential loading.

Only a separately reviewed host adapter may supply the signing key and the
checkpoint-only DB role. The backend package must never copy this module/key.
"""

import os
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from retirement.checkpoint import (
    CheckpointUnavailable,
    DOMAIN,
    MAX_FILE_BYTES,
    RECORD_BYTES,
    payload,
)
from retirement.interlock import LOCK, NAMESPACE, PHYSICAL, RetirementUnavailable


def signed_record(
    private_key, *, installation, key_id, sequence, digest, previous, commitment
):
    if type(private_key) is not Ed25519PrivateKey and not isinstance(
        private_key, Ed25519PrivateKey
    ):
        raise CheckpointUnavailable()
    message = payload(installation, key_id, sequence, digest, previous, commitment)
    return message + private_key.sign(DOMAIN + message)


def publish(protected, conn, private_key):
    """Fsync a single exact next record before host-only DB acknowledgement.

    Caller owns session advisory gate through this function and actual COMMIT.
    A returned raw seal is never a final acknowledgement. For a crash after
    append and before commit, recognize the exact existing signed head and retry
    ONLY its database acknowledgement. Do not append/re-sign another head.
    """
    head = protected.head()
    row = conn.execute(
        "SELECT installation_id,identity_key_id,key_commitment,last_sequence,head_digest,acknowledged_sequence,acknowledged_digest,pending_count FROM retirement.checkpoint()"
    ).fetchone()
    if (
        type(row) is not tuple
        or len(row) != 8
        or str(row[0]) != head.installation
        or str(row[1]) != head.key_id
        or row[2] != head.key_commitment
        or type(row[3]) is not int
        or row[3] not in (head.sequence, head.sequence + 1)
    ):
        raise CheckpointUnavailable()
    if row[3] == head.sequence:
        if row[4] != head.event_digest or row[5] not in (
            head.sequence - 1,
            head.sequence,
        ):
            raise CheckpointUnavailable()
        # Existing bytes must have completed fsync before a retry can acknowledge.
        fd = None
        try:
            fd, before = protected._open(write=True)
            os.fsync(fd)
            protected._unchanged(fd, before)
        finally:
            if fd is not None:
                os.close(fd)
    else:
        if row[5] != head.sequence or row[6] != head.event_digest:
            raise CheckpointUnavailable()
        raw = signed_record(
            private_key,
            installation=head.installation,
            key_id=head.key_id,
            sequence=row[3],
            digest=row[4],
            previous=head.record_digest,
            commitment=head.key_commitment,
        )
        # Verify the supplied host key matches the independently pinned public key
        # BEFORE touching the append-only file. No malformed append can be undone.
        protected._decode(raw)
        fd = None
        try:
            fd, before = protected._open(write=True)
            if (
                before.st_size != (head.sequence + 1) * RECORD_BYTES
                or before.st_size + RECORD_BYTES > MAX_FILE_BYTES
            ):
                raise CheckpointUnavailable()
            started = time.monotonic()
            # One fixed208-byte write. A partial write remains maintenance; never
            # truncate or fill in/re-sign a tail after an uncertain append.
            if os.write(fd, raw) != RECORD_BYTES:
                raise CheckpointUnavailable()
            os.fsync(fd)
            if time.monotonic() - started > 2:
                raise CheckpointUnavailable()
            protected._unchanged(fd, before, size=before.st_size + RECORD_BYTES)
        finally:
            if fd is not None:
                os.close(fd)
        head = protected.head()
        if head.sequence != row[3] or head.event_digest != row[4]:
            raise CheckpointUnavailable()
    conn.execute(
        "SELECT retirement.acknowledge_checkpoint(%s,%s,%s)",
        (head.installation, head.sequence, head.event_digest),
    )
    # The adapter must set synchronous_commit on immediately before its owned
    # COMMIT and return only after successful COMMIT/drain; no ack escapes here.
    return head


class HostPublisher:
    """Fixed one-connection host adapter. Does not open/load a key or pool.

    Full startup scan is compulsory. The dedicated role may acknowledge a head
    but may not insert fingerprints/intents, modify a journal or grant access.
    Pool and exact-role checks remain required in the actual fixture/deployment.
    """

    def __init__(self, pool, protected, private_key):
        self.pool, self.protected, self.private_key = pool, protected, private_key
        self.poisoned = False

    def startup(self):
        return self.protected.head(full=True)

    def once(self):
        if self.poisoned or not PHYSICAL.acquire(timeout=1):
            raise RetirementUnavailable()
        try:
            with self.pool.connection(timeout=1) as conn:
                locked = False
                try:
                    if not conn.autocommit or conn.info.transaction_status != 0:
                        raise RetirementUnavailable()
                    with conn.transaction():
                        conn.execute("SET LOCAL statement_timeout='3s'")
                        if conn.execute("SELECT current_user").fetchone() != (
                            "aqua_retirement_checkpoint",
                        ):
                            raise RetirementUnavailable()
                        if conn.execute(
                            "SELECT pg_try_advisory_lock(%s,%s)", (NAMESPACE, LOCK)
                        ).fetchone() != (True,):
                            raise RetirementUnavailable()
                        locked = True
                    with conn.transaction():
                        conn.execute("SET LOCAL statement_timeout='3s'")
                        conn.execute("SET LOCAL lock_timeout='1s'")
                        conn.execute(
                            "SET LOCAL idle_in_transaction_session_timeout='10s'"
                        )
                        result = publish(self.protected, conn, self.private_key)
                        if conn.info.transaction_status != 2:
                            raise RetirementUnavailable()
                        conn.execute("SET LOCAL synchronous_commit='on'")
                    if conn.info.transaction_status != 0:
                        raise RetirementUnavailable()
                    # Read back only after our actual successful COMMIT while
                    # still owning the same physical and database session gate.
                    with conn.transaction():
                        conn.execute("SET LOCAL statement_timeout='3s'")
                        self.protected.require_current(conn, allow_pending=True)
                    return result
                finally:
                    if locked:
                        try:
                            if conn.info.transaction_status != 0:
                                raise RetirementUnavailable()
                            with conn.transaction():
                                conn.execute("SET LOCAL statement_timeout='3s'")
                                if conn.execute(
                                    "SELECT pg_advisory_unlock(%s,%s)",
                                    (NAMESPACE, LOCK),
                                ).fetchone() != (True,):
                                    raise RetirementUnavailable()
                                if conn.execute(
                                    "SELECT count(*) FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='advisory'"
                                ).fetchone() != (0,):
                                    raise RetirementUnavailable()
                        except BaseException:
                            self.poisoned = True
                            conn.close()
                            raise RetirementUnavailable() from None
        except BaseException as error:
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            raise RetirementUnavailable() from None
        finally:
            PHYSICAL.release()
