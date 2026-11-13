"""Private typed worker/web interface; no pool/key/config opens or activation.

Only ConfirmedRetirement can authorize a later bounded purge. This is not proof
of physical completion. Offline restore reconciliation and protected production
provisioning remain separate admission and activation gates.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from retirement.fingerprints import canonical_uuid
from retirement.intents import Intent
from retirement.interlock import Broker, RetirementUnavailable
from retirement.pages import Manifest, manifest


@dataclass(frozen=True)
class PendingAuthority:
    intent_id: str
    next_page: int
    state: str
    acceptance_confirmed: bool = False


@dataclass(frozen=True)
class PageReceipt:
    ordinal: int
    digest: bytes


@dataclass(frozen=True)
class ManifestSealed:
    intent_id: str
    sequence: int
    event_digest: bytes
    purge_authorized: bool = field(default=False, init=False)


@dataclass(frozen=True)
class LocalCommit:
    value: object
    acceptance_confirmed: bool = field(default=False, init=False)


@dataclass(frozen=True)
class ConfirmedAcceptance:
    record: Intent
    checkpoint_sequence: int
    checkpoint_digest: bytes
    acceptance_confirmed: bool = field(default=True, init=False)
    cleanup_complete: bool = field(default=False, init=False)
    purge_authorized: bool = field(default=False, init=False)


@dataclass(frozen=True)
class ConfirmedRetirement:
    record: Intent
    checkpoint_sequence: int
    checkpoint_digest: bytes
    cleanup_complete: bool = field(default=False, init=False)
    acceptance_confirmed: bool = field(default=True, init=False)
    purge_authorized: bool = field(default=True, init=False)


@dataclass(frozen=True)
class _Snapshot:
    record: Intent
    expected_count: int
    expected_root: bytes
    state: str
    next_page: int


def _time(value):
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise RetirementUnavailable()
    return value.astimezone(timezone.utc)


def _metadata(record):
    return (
        record.installation,
        record.owner,
        record.intent,
        record.job,
        record.scope,
        record.created_at,
        record.history_floor,
        record.privacy_floor,
        record.auth_floor,
        record.closed,
        record.fingerprint_count,
        record.fingerprint_root,
    )


class AuthorityClient:
    def __init__(self, broker):
        if type(broker) is not Broker:
            raise RetirementUnavailable()
        self.broker = broker

    def startup_checkpoint(self):
        return self.broker.startup_checkpoint()

    def _lookup(self, conn, intent_id):
        canonical_uuid(intent_id)
        row = conn.execute(
            "SELECT installation_id,intent_id,owner_id,job_id,created_at,scope,history_floor,privacy_floor,auth_floor,account_closed,expected_count,expected_pages,expected_root,state,next_page,page_head,sequence,event_digest,checkpointed_at,sealed_at FROM retirement.lookup_intent(%s)",
            (intent_id,),
        ).fetchone()
        if row is None:
            return None
        if (
            type(row) is not tuple
            or len(row) != 20
            or str(row[0]) != self.broker.installation
            or str(row[1]) != intent_id
            or type(row[10]) is not int
            or not 0 <= row[10] <= 100000
            or type(row[11]) is not int
            or row[11] != (row[10] + 127) // 128
            or type(row[12]) is not bytes
            or len(row[12]) != 32
            or row[13] not in {"staging", "sealed"}
            or type(row[14]) is not int
            or not 0 <= row[14] <= row[11]
            or type(row[15]) is not bytes
            or len(row[15]) != 32
        ):
            raise RetirementUnavailable()
        if (
            type(row[16]) is not int
            or not 1 <= row[16] <= 250000
            or type(row[17]) is not bytes
            or len(row[17]) != 32
        ):
            raise RetirementUnavailable()
        if row[13] == "sealed" and (
            row[14] != row[11]
            or row[15] != row[12]
            or row[19] is None
            or row[18] is None
        ):
            raise RetirementUnavailable()
        if row[13] == "sealed" and _time(row[19]) < _time(row[4]):
            raise RetirementUnavailable()
        if row[13] == "staging" and row[19] is not None:
            raise RetirementUnavailable()
        # The single immutable header exists from begin. Header acceptance and
        # complete-manifest purge authorization remain separate checked types.
        confirmed = row[18] is not None
        record = Intent(
            str(row[0]),
            str(row[2]),
            str(row[1]),
            str(row[3]),
            row[5],
            _time(row[4]),
            row[6],
            row[7],
            row[8],
            row[9],
            row[16] if confirmed else None,
            row[17] if confirmed else None,
            _time(row[18]) if confirmed else None,
            row[10],
            row[12],
        )
        return _Snapshot(record, row[10], row[12], row[13], row[14])

    def intent_transaction(self, storage, owner_id, intent_id, scope, apply):
        """Exact known-intent/absence read stays gated through local app COMMIT.

        The reviewed callback rechecks current user/status, local tombstone,
        proof and finite job/intent admission. No authority mutation occurs while
        it holds app row locks. No proof is consumed for an already known intent.
        """
        canonical_uuid(owner_id)
        canonical_uuid(intent_id)
        if scope not in {"chat_history_v1", "account_v1"}:
            raise RetirementUnavailable()
        with self.broker._session() as conn:
            with conn.transaction():
                conn.execute("SET LOCAL statement_timeout='3s'")
                self.broker.checkpoint.require_current(conn, allow_pending=True)
                known = self._lookup(conn, intent_id)
                if known is not None and (known.record.owner, known.record.scope) != (
                    owner_id,
                    scope,
                ):
                    raise RetirementUnavailable()
            with storage.transaction() as app:
                result = apply(app, known.record if known else None)
            return LocalCommit(result)

    def prepare(self, record, fingerprint_manifest):
        if (
            type(record) is not Intent
            or record.installation != self.broker.installation
            or record.sequence is not None
            or type(fingerprint_manifest) is not Manifest
            or type(fingerprint_manifest.count) is not int
            or not 0 <= fingerprint_manifest.count <= 100000
            or type(fingerprint_manifest.root) is not bytes
            or len(fingerprint_manifest.root) != 32
            or type(fingerprint_manifest.pages) is not tuple
            or len(fingerprint_manifest.pages) > 782
            or any(
                type(page) is not tuple or not 1 <= len(page) <= 128
                for page in fingerprint_manifest.pages
            )
        ):
            raise RetirementUnavailable()
        # Recompute canonical bounded page structure/root, not just its declared
        # count. This is synthetic/server metadata, never caller HTTP content.
        checked = manifest(item for page in fingerprint_manifest.pages for item in page)
        if checked != fingerprint_manifest:
            raise RetirementUnavailable()
        if (record.fingerprint_count, record.fingerprint_root) != (
            checked.count,
            checked.root,
        ):
            raise RetirementUnavailable()

        def apply(conn):
            conn.execute(
                "SELECT retirement.begin_intent(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    record.installation,
                    record.intent,
                    record.owner,
                    record.job,
                    record.created_at,
                    record.scope,
                    record.history_floor,
                    record.privacy_floor,
                    record.auth_floor,
                    checked.count,
                    checked.root,
                ),
            )
            known = self._lookup(conn, record.intent)
            if (
                known is None
                or _metadata(known.record) != _metadata(record)
                or known.expected_count != checked.count
                or known.expected_root != checked.root
            ):
                raise RetirementUnavailable()
            return PendingAuthority(record.intent, known.next_page, known.state)

        return self.broker.authority_transaction(apply)

    def append_page(self, intent_id, ordinal, previous_digest, entries):
        canonical_uuid(intent_id)
        if (
            type(ordinal) is not int
            or not 0 <= ordinal < 782
            or type(previous_digest) is not bytes
            or len(previous_digest) != 32
            or type(entries) is not tuple
            or not 1 <= len(entries) <= 128
            or any(type(item) is not bytes or len(item) != 114 for item in entries)
        ):
            raise RetirementUnavailable()

        def apply(conn):
            row = conn.execute(
                "SELECT retirement.append_page(%s,%s,%s,%s,%s)",
                (
                    self.broker.installation,
                    intent_id,
                    ordinal,
                    previous_digest,
                    list(entries),
                ),
            ).fetchone()
            if (
                type(row) is not tuple
                or len(row) != 1
                or type(row[0]) is not bytes
                or len(row[0]) != 32
            ):
                raise RetirementUnavailable()
            return PageReceipt(ordinal, row[0])

        return self.broker.authority_transaction(apply)

    def seal(self, intent_id):
        canonical_uuid(intent_id)

        def apply(conn):
            row = conn.execute(
                "SELECT * FROM retirement.seal_intent(%s,%s)",
                (self.broker.installation, intent_id),
            ).fetchone()
            if (
                type(row) is not tuple
                or len(row) != 2
                or type(row[0]) is not int
                or not 1 <= row[0] <= 250000
                or type(row[1]) is not bytes
                or len(row[1]) != 32
            ):
                raise RetirementUnavailable()
            return ManifestSealed(intent_id, row[0], row[1])

        return self.broker.authority_transaction(apply)

    def _confirm(self, owner_id, intent_id, scope, *, acceptance_only):
        canonical_uuid(owner_id)
        canonical_uuid(intent_id)
        if scope not in {"chat_history_v1", "account_v1"}:
            raise RetirementUnavailable()
        with self.broker._session() as conn:
            with conn.transaction():
                conn.execute("SET LOCAL statement_timeout='3s'")
                head = self.broker.checkpoint.require_current(conn, allow_pending=True)
                known = self._lookup(conn, intent_id)
                if known is None or (known.record.owner, known.record.scope) != (
                    owner_id,
                    scope,
                ):
                    raise RetirementUnavailable()
                if (
                    known.record.sequence is None
                    or known.record.sequence > head.sequence
                ):
                    raise RetirementUnavailable()
                if acceptance_only:
                    return ConfirmedAcceptance(
                        known.record, head.sequence, head.event_digest
                    )
                if known.state == "staging":
                    return PendingAuthority(
                        intent_id, known.next_page, known.state, True
                    )
                return ConfirmedRetirement(
                    known.record, head.sequence, head.event_digest
                )

    def confirm_acceptance(self, owner_id, intent_id, scope):
        return self._confirm(owner_id, intent_id, scope, acceptance_only=True)

    def confirm(self, owner_id, intent_id, scope):
        return self._confirm(owner_id, intent_id, scope, acceptance_only=False)

    def grant_transaction(self, storage, dataset_key, candidates, apply):
        return self.broker.grant_transaction(storage, dataset_key, candidates, apply)
