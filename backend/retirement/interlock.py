"""Private P11bc overlay: physical one-process authority/app-commit interlock.

No pool opens here. A separately reviewed dedicated max-one checked retirement
pool and strict one-web-process activation are prerequisites. No DB-only lock or
lease expiry releases a physical operation. This module is not activated.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import hmac
import threading

from retirement.fingerprints import Fingerprint, IdentityKey, canonical_uuid
from retirement.checkpoint import ProtectedFile

PHYSICAL = threading.Lock()
ACQUIRE_SECONDS = 1.0
NAMESPACE = 1095848273
LOCK = 1


class RetirementUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("retirement_authority_unavailable")


@dataclass(frozen=True)
class GrantDecision:
    installation: str
    dataset_key: str
    retired: bool


class Broker:
    def __init__(self, pool, installation, *, key, checkpoint):
        if type(key) is not IdentityKey or type(checkpoint) is not ProtectedFile:
            raise RetirementUnavailable()
        self.pool = pool
        self.installation = canonical_uuid(installation)
        self.key = key
        self.checkpoint = checkpoint
        self.poisoned = False

    @contextmanager
    def _session(self):
        # This registry is shared across every pool/Broker instance in the only
        # permitted process. Acquiring the DB session is never a TTL recovery.
        if self.poisoned or not PHYSICAL.acquire(timeout=ACQUIRE_SECONDS):
            raise RetirementUnavailable()
        try:
            if self.poisoned:
                raise RetirementUnavailable()
            with self.pool.connection(timeout=1.0) as conn:
                locked = False
                try:
                    if not conn.autocommit or conn.info.transaction_status != 0:
                        raise RetirementUnavailable()
                    with conn.transaction():
                        conn.execute("SET LOCAL statement_timeout='3s'")
                        conn.execute("SET LOCAL lock_timeout='1s'")
                        conn.execute(
                            "SET LOCAL idle_in_transaction_session_timeout='10s'"
                        )
                        row = conn.execute(
                            "SELECT pg_try_advisory_lock(%s,%s)", (NAMESPACE, LOCK)
                        ).fetchone()
                        if row != (True,):
                            raise RetirementUnavailable()
                        locked = True
                        identity = conn.execute(
                            "SELECT installation_id,identity_key_id,key_commitment FROM retirement.identity_context()"
                        ).fetchone()
                        if (
                            type(identity) is not tuple
                            or len(identity) != 3
                            or str(identity[0]) != self.installation
                            or str(identity[1]) != self.key.key_id
                            or type(identity[2]) is not bytes
                            or not hmac.compare_digest(identity[2], self.key.commitment)
                        ):
                            raise RetirementUnavailable()
                    yield conn
                finally:
                    try:
                        if locked:
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
                        # Synchronous close ends this DB session before the
                        # physical claim is released. No replacement session
                        # turns a still-draining application commit into free work.
                        self.poisoned = True
                        conn.close()
                        raise RetirementUnavailable() from None
        except BaseException as error:
            if isinstance(error, RetirementUnavailable):
                raise
            raise RetirementUnavailable() from None
        finally:
            PHYSICAL.release()

    def _decision(self, conn, dataset_key, candidates):
        if (
            type(dataset_key) is not str
            or not 1 <= len(dataset_key) <= 128
            or type(candidates) is not tuple
            or len(candidates) != 2
            or any(type(value) is not Fingerprint for value in candidates)
            or tuple(value.kind for value in candidates)
            != ("google_subject", "mailbox")
            or candidates[0].key_id != candidates[1].key_id
            or candidates[0].key_id != self.key.key_id
        ):
            raise RetirementUnavailable()
        with conn.transaction():
            conn.execute("SET LOCAL statement_timeout='3s'")
            row = conn.execute(
                "SELECT installation_id,retired FROM retirement.check_google_grant(%s,%s,%s,%s,%s)",
                (
                    self.installation,
                    dataset_key,
                    candidates[0].key_id,
                    candidates[0].digest,
                    candidates[1].digest,
                ),
            ).fetchone()
        if (
            type(row) is not tuple
            or len(row) != 2
            or str(row[0]) != self.installation
            or type(row[1]) is not bool
        ):
            raise RetirementUnavailable()
        return GrantDecision(self.installation, dataset_key, row[1])

    def startup_checkpoint(self):
        """Full protected-file scan/current DB binding before any public writer."""
        with self._session() as conn:
            scanned = self.checkpoint.head(full=True)
            with conn.transaction():
                conn.execute("SET LOCAL statement_timeout='3s'")
                # A protected accepted header may still have its immutable
                # manifest upload in flight. Startup validates the app mirror
                # before its worker resumes; grants remain independently closed
                # until every manifest is sealed.
                current = self.checkpoint.require_current(conn, allow_pending=True)
                if current != scanned:
                    raise RetirementUnavailable()
                return current

    def grant_transaction(self, storage, dataset_key, candidates, apply):
        """Own nesting: independent gate -> short app TX -> commit -> release.

        apply is a reviewed synchronous adapter, never supplied by an API. It
        rechecks the current canonical user/identity under the existing user
        guard, skips automatic INSERT when decision.retired and creates a session
        only under the chosen account/analytics policy. It must not spawn work.
        """
        with self._session() as conn:
            with conn.transaction():
                conn.execute("SET LOCAL statement_timeout='3s'")
                self.checkpoint.require_current(conn)
            decision = self._decision(conn, dataset_key, candidates)
            with storage.transaction() as app:
                result = apply(app, decision)
            # storage.transaction's commit/rollback and driver cleanup completed
            # before this return can release the independent physical claim.
            return result

    def authority_transaction(self, apply):
        """Serialize a validated append/checkpoint operation with grant commits.

        Caller must release all app row guards before entering. Exact append,
        durable acknowledgement and immutable-intent SQL need independent actual
        PostgreSQL tests; this method does not assert those guarantees itself.
        """
        with self._session() as conn:
            if conn.info.transaction_status != 0:
                raise RetirementUnavailable()
            with conn.transaction():
                conn.execute("SET LOCAL statement_timeout='3s'")
                conn.execute("SET LOCAL lock_timeout='1s'")
                conn.execute("SET LOCAL idle_in_transaction_session_timeout='10s'")
                self.checkpoint.require_current(conn, allow_pending=True)
                result = apply(conn)
                if conn.info.transaction_status != 2:
                    raise RetirementUnavailable()
                # A SECURITY DEFINER function cannot prevent its caller from
                # setting synchronous_commit off afterwards. Own the final
                # setting immediately before our managed COMMIT, then verify
                # IDLE after it. There is no user callback between these steps.
                conn.execute("SET LOCAL synchronous_commit='on'")
            if conn.info.transaction_status != 0:
                raise RetirementUnavailable()
            return result
