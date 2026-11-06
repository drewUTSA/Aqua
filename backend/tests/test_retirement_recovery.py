"""Actual restored-app SQL; independent responses are explicit synthetic fixtures."""

from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace

import pytest

from retirement.checkpoint import ZERO
from retirement.interlock import RetirementUnavailable
from retirement.pages import INITIAL, page_digest
from retirement.recovery import event_digest, reconcile
from retirement.startup import validate
from test_deletion_lifecycle import deletion as deletion_fixture, request

deletion = deletion_fixture


class RecoveryConnection:
    autocommit = True
    info = SimpleNamespace(transaction_status=0)

    def __init__(self, authority):
        self.events, self.pages = [], {}
        previous = ZERO
        for sequence, original in enumerate(authority.originals.values(), 1):
            accepted = authority.confirm_acceptance(
                original.owner, original.intent, original.scope
            ).record
            record = replace(accepted, sequence=sequence, event_digest=ZERO)
            record = replace(record, event_digest=event_digest(record, previous))
            sealed = record.intent in authority.sealed
            self.events.append(
                (
                    sequence,
                    previous,
                    record.event_digest,
                    record.intent,
                    record.owner,
                    record.job,
                    record.created_at,
                    record.checkpointed_at,
                    record.checkpointed_at if sealed else None,
                    "sealed" if sealed else "staging",
                    record.scope,
                    record.history_floor,
                    record.privacy_floor,
                    record.auth_floor,
                    record.closed,
                    record.fingerprint_count,
                    record.fingerprint_root,
                )
            )
            digest = INITIAL
            pages = []
            for ordinal, values in enumerate(authority.pages[record.intent]):
                current = page_digest(digest, ordinal, tuple(values))
                pages.append((ordinal, digest, current, list(values)))
                digest = current
            self.pages[record.intent] = pages
            previous = record.event_digest
        self.head = SimpleNamespace(
            installation=authority.broker.installation,
            key_id=authority.broker.key.key_id,
            sequence=len(self.events),
            event_digest=previous,
        )

    def execute(self, sql, values=()):
        if "FROM pg_roles" in sql:
            result = (
                "aqua_retirement",
                "aqua_retirement_recovery",
                False,
                False,
                False,
                False,
                False,
                False,
                1,
            )
        elif "pg_try_advisory_lock" in sql or "pg_advisory_unlock" in sql:
            result = (True,)
        elif "read_events" in sql:
            return SimpleNamespace(
                fetchall=lambda: [row for row in self.events if row[0] > values[0]][
                    :128
                ]
            )
        elif "read_pages" in sql:
            return SimpleNamespace(
                fetchall=lambda: [
                    row for row in self.pages[values[0]] if row[0] > values[1]
                ][:4]
            )
        else:
            raise AssertionError("unexpected synthetic recovery SQL")
        return SimpleNamespace(fetchone=lambda: result)

    def close(self):
        raise AssertionError("unexpected synthetic recovery connection corruption")


def restored(deletion, app_database, scope="chat_history_v1", *, seal=True):
    secure, authority, service, worker = deletion
    client, owner = secure.client(linked=True)
    secure.world.submit(client, "A backup must not resurrect this private answer")
    body = request(secure, client, owner, scope)
    assert client.post("/api/v1/me/data-deletions", json=body).status_code == 202
    if seal:
        original = authority.originals[body["intent_id"]]
        with service.storage.transaction() as conn:
            raw = conn.execute("SELECT manifest FROM app.deletion_jobs").fetchone()[0]
        from retirement.original_manifest import decode_original

        fingerprints = decode_original(
            bytes(raw), original, key_id=authority.broker.key.key_id
        )
        for ordinal, values in enumerate(fingerprints.pages):
            authority.append_page(original.intent, ordinal, INITIAL, values)
        authority.seal(original.intent)
    recovery = RecoveryConnection(authority)
    # Simulate a consistent app backup from BEFORE the deletion transaction.
    # Only this fixture migration owner can remove immutable metadata.
    app_database.execute("SET ROLE aqua_app_owner")
    for table, trigger in (
        ("deletion_jobs", "deletion_job_immutable"),
        ("retirement_intents", "retirement_intent_immutable"),
    ):
        app_database.execute(f"ALTER TABLE app.{table} DISABLE TRIGGER {trigger}")
        app_database.execute(f"DELETE FROM app.{table}")
        app_database.execute(f"ALTER TABLE app.{table} ENABLE TRIGGER {trigger}")
    app_database.execute(
        "UPDATE app.users SET history_generation=1,privacy_epoch=1,auth_epoch=0,status='active'"
    )
    app_database.execute(
        "UPDATE app.retirement_control SET permanent_intents=0,manifest_bytes=0,recovery_required=false"
    )
    app_database.execute("RESET ROLE")
    with service.storage.transaction() as conn:
        conn.execute("UPDATE app.sessions SET revoked_at=clock_timestamp()")
    protected = SimpleNamespace(require_current=lambda conn, **kwargs: recovery.head)
    return secure, service, owner, recovery, protected


@pytest.mark.parametrize("scope", ("chat_history_v1", "account_v1"))
def test_app_only_restore_replays_original_signed_floors_and_bounded_purge_before_ready(
    deletion, app_database, scope
):
    secure, service, owner, recovery, protected = restored(
        deletion, app_database, scope
    )
    first = reconcile(
        service.storage,
        recovery,
        protected,
        purge_guard=lambda closed: nullcontext(True),
        batch_limit=1,
    )
    assert first.ready is False and first.purge_batches == 1
    with pytest.raises(RetirementUnavailable):
        validate(service.storage, service.runtime.client, recovery.head)
    result = reconcile(
        service.storage,
        recovery,
        protected,
        purge_guard=lambda closed: nullcontext(True),
    )
    assert result.ready is True and result.events_verified == 1
    with service.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.chats WHERE user_id=%s", (owner,)
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM app.visual_results WHERE user_id=%s", (owner,)
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT permanent_intents,manifest_bytes,recovery_required FROM app.retirement_control"
        ).fetchone() == (1, 0, False)
        assert conn.execute(
            "SELECT history_floor,privacy_floor,account_closed FROM app.retirement_intents"
        ).fetchone() == (2, 2, scope == "account_v1")
        if scope == "account_v1":
            assert (
                conn.execute("SELECT 1 FROM app.users WHERE id=%s", (owner,)).fetchone()
                is None
            )
        else:
            assert conn.execute(
                "SELECT history_generation,privacy_epoch FROM app.users WHERE id=%s",
                (owner,),
            ).fetchone() == (2, 2)
            assert (
                conn.execute(
                    "SELECT 1 FROM app.sessions WHERE revoked_at IS NULL LIMIT 1"
                ).fetchone()
                is None
            )
    validate(service.storage, service.runtime.client, recovery.head)


def test_unsealed_missing_original_stays_in_persistent_maintenance_without_purge(
    deletion, app_database
):
    secure, service, owner, recovery, protected = restored(
        deletion, app_database, seal=False
    )
    result = reconcile(
        service.storage,
        recovery,
        protected,
        purge_guard=lambda closed: nullcontext(True),
    )
    assert result.ready is False and result.pending_manifest is True
    with service.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.chats WHERE user_id=%s", (owner,)
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT recovery_required FROM app.retirement_control"
        ).fetchone() == (True,)
    with pytest.raises(RetirementUnavailable):
        validate(service.storage, service.runtime.client, recovery.head)


def test_missing_independent_event_cannot_self_attest_recovery_completion(
    deletion, app_database
):
    secure, service, owner, recovery, protected = restored(deletion, app_database)
    recovery.events = []
    with pytest.raises(RetirementUnavailable):
        reconcile(
            service.storage,
            recovery,
            protected,
            purge_guard=lambda closed: nullcontext(True),
        )
    with service.storage.transaction() as conn:
        assert conn.execute(
            "SELECT recovery_required FROM app.retirement_control"
        ).fetchone() == (True,)
        assert conn.execute(
            "SELECT history_generation FROM app.users WHERE id=%s", (owner,)
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT count(*) FROM app.chats WHERE user_id=%s", (owner,)
        ).fetchone() == (1,)


def test_restore_cannot_open_before_existing_session_fence(deletion, app_database):
    secure, service, owner, recovery, protected = restored(deletion, app_database)
    with service.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.sessions SET revoked_at=NULL WHERE user_id=%s", (owner,)
        )
    with pytest.raises(RetirementUnavailable):
        reconcile(
            service.storage,
            recovery,
            protected,
            purge_guard=lambda closed: nullcontext(True),
        )


def test_accepted_account_restore_cleans_even_a_newer_local_generation(
    deletion, app_database
):
    secure, service, owner, recovery, protected = restored(
        deletion, app_database, "account_v1"
    )
    with service.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.chats SET history_generation=5 WHERE user_id=%s", (owner,)
        )
        conn.execute(
            "UPDATE app.analysis_jobs SET history_generation=5 WHERE user_id=%s",
            (owner,),
        )
        conn.execute("UPDATE app.users SET history_generation=5 WHERE id=%s", (owner,))
    result = reconcile(
        service.storage,
        recovery,
        protected,
        purge_guard=lambda closed: nullcontext(True),
    )
    assert result.ready is True
    with service.storage.transaction() as conn:
        assert (
            conn.execute("SELECT 1 FROM app.users WHERE id=%s", (owner,)).fetchone()
            is None
        )
        assert conn.execute(
            "SELECT content_bytes FROM app.workspace_totals"
        ).fetchone() == (0,)
