"""Private overlay: immutable retirement intents outlive visible job expiry.

Application migration9 and the separately installed independent SQL retain the
same immutable original metadata. An Intent must come from authenticated or
reconciled authority, never request JSON. Acknowledgement is not proof that
physical cleanup completed.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from retirement.fingerprints import canonical_uuid
from retirement.pages import INITIAL

MAX_EPOCH = 9007199254740991
SCOPES = frozenset({"chat_history_v1", "account_v1"})


class IntentConflict(RuntimeError):
    def __init__(self):
        super().__init__("retirement_intent_conflict")


@dataclass(frozen=True)
class Intent:
    installation: str
    owner: str
    intent: str
    job: str
    scope: str
    created_at: datetime
    history_floor: int
    privacy_floor: int
    auth_floor: int
    closed: bool
    sequence: int | None = None
    event_digest: bytes | None = None
    checkpointed_at: datetime | None = None
    fingerprint_count: int = 0
    fingerprint_root: bytes = INITIAL

    def __post_init__(self):
        for value in (self.installation, self.owner, self.intent, self.job):
            canonical_uuid(value)
        present = (
            self.sequence is not None,
            self.event_digest is not None,
            self.checkpointed_at is not None,
        )
        if (
            self.scope not in SCOPES
            or type(self.closed) is not bool
            or self.closed != (self.scope == "account_v1")
            or not isinstance(self.created_at, datetime)
            or self.created_at.utcoffset() != timedelta(0)
            or any(present)
            and not all(present)
            or all(present)
            and (
                type(self.sequence) is not int
                or not 1 <= self.sequence <= 250000
                or type(self.event_digest) is not bytes
                or len(self.event_digest) != 32
                or not isinstance(self.checkpointed_at, datetime)
                or self.checkpointed_at.utcoffset() != timedelta(0)
                or self.checkpointed_at < self.created_at
            )
            or any(
                type(value) is not int or not 2 <= value <= MAX_EPOCH
                for value in (self.history_floor, self.privacy_floor)
            )
            or type(self.auth_floor) is not int
            or not 0 <= self.auth_floor <= MAX_EPOCH
            or self.closed
            and self.auth_floor < 1
            or type(self.fingerprint_count) is not int
            or not 0 <= self.fingerprint_count <= 100000
            or type(self.fingerprint_root) is not bytes
            or len(self.fingerprint_root) != 32
            or self.closed
            and self.fingerprint_count < 1
            or not self.closed
            and (self.fingerprint_count != 0 or self.fingerprint_root != INITIAL)
        ):
            raise IntentConflict()


@dataclass(frozen=True)
class Replay:
    action: str
    history_floor: int
    job: str
    created_at: datetime
    updated_at: datetime
    cleanup_complete: bool = field(default=False, init=False)
    acceptance_confirmed: bool = field(default=True, init=False)


def replay(known, *, installation, owner, intent, scope):
    """An old intent can select only its original floor, never today's history.

    This intentionally has no current-generation input or 'create' return. A
    separately checked absence in BOTH the app tombstone and complete authority
    is required before admitting a new intent under its current app user lock.
    """
    if (
        type(known) is not Intent
        or known.checkpointed_at is None
        or (
            known.installation,
            known.owner,
            known.intent,
            known.scope,
        )
        != (installation, owner, intent, scope)
    ):
        raise IntentConflict()
    return Replay(
        "replay_pending",
        known.history_floor,
        known.job,
        known.created_at,
        known.created_at,
    )


def reconcile_tombstone(conn, known):
    """Insert missing minimal app metadata without altering an existing intent.

    Caller owns a short app transaction after validating the independent event.
    Only one-way missing manifest/ACK metadata can be filled; no general mutation,
    DELETE/expiry or user-content path exists. Restore
    must run this before opening writers; runtime cannot infer ledger completeness.
    """
    if type(known) is not Intent:
        raise IntentConflict()
    values = (
        known.installation,
        known.owner,
        known.intent,
        known.job,
        known.scope,
        known.created_at,
        known.history_floor,
        known.privacy_floor,
        known.auth_floor,
        known.closed,
        known.fingerprint_count,
        known.fingerprint_root,
        known.sequence,
        known.event_digest,
        known.checkpointed_at,
    )
    conn.execute(
        "INSERT INTO app.retirement_intents(installation_id,user_id,intent_id,job_id,scope,created_at,history_floor,privacy_floor,auth_floor,account_closed,fingerprint_count,fingerprint_root,authority_sequence,event_digest,checkpointed_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(installation_id,user_id,intent_id) DO NOTHING",
        values,
    )
    row = conn.execute(
        "SELECT installation_id::text,user_id::text,intent_id::text,job_id::text,scope,created_at,history_floor,privacy_floor,auth_floor,account_closed,fingerprint_count,fingerprint_root,authority_sequence,event_digest,checkpointed_at FROM app.retirement_intents WHERE installation_id=%s AND user_id=%s AND intent_id=%s FOR UPDATE",
        values[:3],
    ).fetchone()
    if row is None or row[:10] != values[:10]:
        raise IntentConflict()
    if row[10:12] == (None, None):
        changed = conn.execute(
            "UPDATE app.retirement_intents SET fingerprint_count=%s,fingerprint_root=%s WHERE installation_id=%s AND user_id=%s AND intent_id=%s AND fingerprint_count IS NULL AND fingerprint_root IS NULL RETURNING fingerprint_count,fingerprint_root",
            values[10:12] + values[:3],
        ).fetchone()
        if changed != values[10:12]:
            raise IntentConflict()
        row = row[:10] + values[10:12] + row[12:]
    elif row[10:12] != values[10:12]:
        raise IntentConflict()
    if row[12:] == (None, None, None) and values[12:] != (None, None, None):
        changed = conn.execute(
            "UPDATE app.retirement_intents SET authority_sequence=%s,event_digest=%s,checkpointed_at=%s WHERE installation_id=%s AND user_id=%s AND intent_id=%s AND authority_sequence IS NULL AND event_digest IS NULL AND checkpointed_at IS NULL RETURNING authority_sequence,event_digest,checkpointed_at",
            values[12:] + values[:3],
        ).fetchone()
        if changed != values[12:]:
            raise IntentConflict()
    elif row != values:
        raise IntentConflict()
    return replay(
        known,
        installation=known.installation,
        owner=known.owner,
        intent=known.intent,
        scope=known.scope,
    )
