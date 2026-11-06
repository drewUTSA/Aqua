"""Synthetic dedicated-DB SQL tests, not complete application deletion proof.

Runs only inside the run-owned network-none fixture. No env/real credentials,
key files, providers, user content, activation or production authority is used.
The one explicit fake checkpoint seam tests real Broker COMMIT failure only;
it does not claim protected-file durability or grant activation.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from uuid import UUID

import psycopg
from psycopg_pool import ConnectionPool

sys.path.insert(0, str(Path(__file__).parent / "backend-sources"))
from retirement.checkpoint import ProtectedFile
from retirement.fingerprints import IdentityKey, ISSUER
from retirement.interlock import Broker, RetirementUnavailable
from retirement.intents import Intent, reconcile_tombstone
from retirement.pages import INITIAL, encode, manifest, page_digest

INSTALLATION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
KEY_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
KEY = IdentityKey(KEY_ID, b"synthetic-fixture-HMAC-key-only!".ljust(32, b"0"))
DATASET = "a" * 64
CREATED = datetime(2026, 10, 30, tzinfo=timezone.utc)
RESULTS = []


def identifier(value):
    return str(UUID(int=value, version=4))


def dsn(role, *, database="aqua_retirement"):
    if role not in {
        "aqua_retirement_writer",
        "aqua_retirement_recovery",
        "aqua_retirement_checkpoint",
        "aqua_app_runtime",
    }:
        raise AssertionError("fixture_role_not_allowed")
    return f"host=/run/aqua-app-db port=5432 dbname={database} user={role} password=fixture-only sslmode=disable"


def connect(role, *, database="aqua_retirement"):
    return psycopg.connect(
        dsn(role, database=database), autocommit=True, connect_timeout=3
    )


def passed(name):
    assert name not in RESULTS
    RESULTS.append(name)


def deny(conn, statement, arguments=(), *, state):
    try:
        with conn.transaction():
            conn.execute(statement, arguments)
    except psycopg.Error as error:
        assert error.sqlstate == state
    else:
        raise AssertionError("fixture_expected_SQL_denial_missing")


def begin(
    conn, intent, owner, job, *, scope="chat_history_v1", floor=2, count=0, root=INITIAL
):
    return conn.execute(
        "SELECT retirement.begin_intent(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            INSTALLATION,
            identifier(intent),
            identifier(owner),
            identifier(job),
            CREATED,
            scope,
            floor,
            floor,
            1 if scope == "account_v1" else 0,
            count,
            root,
        ),
    ).fetchone()[0]


def seal(conn, intent):
    with conn.transaction():
        value = conn.execute(
            "SELECT * FROM retirement.seal_intent(%s,%s)",
            (INSTALLATION, identifier(intent)),
        ).fetchone()
        # The owner adapter must restore this final setting even if a caller
        # changed it after a SECURITY DEFINER function returned.
        conn.execute("SET LOCAL synchronous_commit='off'")
        assert conn.execute("SHOW synchronous_commit").fetchone() == ("off",)
        conn.execute("SET LOCAL synchronous_commit='on'")
    assert conn.info.transaction_status == 0
    return value


def acknowledge(conn, sequence, digest):
    with conn.transaction():
        conn.execute(
            "SELECT retirement.acknowledge_checkpoint(%s,%s,%s)",
            (INSTALLATION, sequence, digest),
        )
        conn.execute("SET LOCAL synchronous_commit='on'")
    assert conn.info.transaction_status == 0


def acknowledge_header(conn):
    value = conn.execute(
        "SELECT last_sequence,head_digest FROM retirement.checkpoint()"
    ).fetchone()
    acknowledge(conn, *value)
    return value


def suite():
    with (
        connect("aqua_retirement_writer") as writer,
        connect("aqua_retirement_checkpoint") as checkpoint,
        connect("aqua_retirement_recovery") as recovery,
    ):
        role = writer.execute(
            "SELECT rolsuper,rolinherit,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolconnlimit FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        assert role == (False, False, False, False, False, False, 1)
        assert writer.execute("SHOW fsync").fetchone() == ("on",)
        assert writer.execute("SHOW full_page_writes").fetchone() == ("on",)
        passed("dedicated_nonprivileged_role_and_durability_settings")
        for sql in (
            "SELECT * FROM retirement.control",
            "DELETE FROM retirement.intents",
            "TRUNCATE retirement.journal",
            "CREATE TABLE retirement.forbidden(x int)",
            "CREATE TEMP TABLE forbidden(x int)",
            "SET ROLE aqua_retirement_owner",
            "SELECT retirement.fixture_default_acl_sentinel()",
            "SELECT retirement.acknowledge_checkpoint('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',0,decode(repeat('00',32),'hex'))",
        ):
            deny(writer, sql, state="42501")
        passed("writer_no_table_DML_DDL_truncate_temp_escalation_or_ack")
        deny(recovery, "SELECT * FROM retirement.control", state="42501")
        deny(checkpoint, "SELECT retirement.writer_guard()", state="42501")
        passed("recovery_checkpoint_roles_do_not_inherit_writer_power")
        try:
            with connect("aqua_app_runtime"):
                raise AssertionError("cross_database_login_permitted")
        except psycopg.OperationalError:
            pass
        passed("app_role_cannot_connect_to_authority")
        try:
            begin(writer, 1, 101, 201)
        except psycopg.Error as error:
            assert error.sqlstate == "55000"
        else:
            raise AssertionError("genesis_ack_missing_not_denied")
        acknowledge(checkpoint, 0, bytes(32))
        passed("genesis_requires_separate_host_role_ack")
        assert begin(writer, 1, 101, 201) == "staging"
        assert checkpoint.execute(
            "SELECT last_sequence,acknowledged_sequence,pending_count FROM retirement.checkpoint()"
        ).fetchone() == (1, 0, 1)
        deny(
            writer,
            "SELECT * FROM retirement.seal_intent(%s,%s)",
            (INSTALLATION, identifier(1)),
            state="55000",
        )
        acknowledge_header(checkpoint)
        assert begin(writer, 1, 101, 201) == "staging"
        passed("same_header_replay_keeps_original_job_and_time")
        for job, floor in ((202, 2), (201, 3)):
            try:
                begin(writer, 1, 101, job, floor=floor)
            except psycopg.Error as error:
                assert error.sqlstate == "23514"
            else:
                raise AssertionError("header_substitution_permitted")
        try:
            begin(writer, 3, 101, 203, floor=3)
        except psycopg.Error as error:
            assert error.sqlstate == "55000"
        else:
            raise AssertionError("second_owner_pending_permitted")
        passed("immutable_substitution_and_second_pending_owner_denied")
        deny(
            writer,
            "SELECT * FROM retirement.check_google_grant(%s,%s,%s,%s,%s)",
            (INSTALLATION, DATASET, KEY_ID, b"x" * 32, b"y" * 32),
            state="55000",
        )
        first = seal(writer, 1)
        assert first[0] == 1
        assert checkpoint.execute(
            "SELECT last_sequence,acknowledged_sequence,pending_count FROM retirement.checkpoint()"
        ).fetchone() == (1, 1, 0)
        passed("header_event_anchors_before_seal_and_seal_never_advances_sequence")
        deny(
            checkpoint,
            "SELECT retirement.acknowledge_checkpoint(%s,%s,%s)",
            (INSTALLATION, 1, b"z" * 32),
            state="23514",
        )
        acknowledge(checkpoint, *first)
        acknowledge(checkpoint, *first)
        passed("checkpoint_exact_replay_and_changed_head_denial")
        payloads = [
            encode(DATASET, KEY.google(ISSUER, "SyntheticSubject" + str(index)))
            for index in range(127)
        ]
        payloads += [
            encode(DATASET, KEY.mailbox("owner@example.test")),
            encode(DATASET, KEY.mailbox("other@example.test")),
        ]
        data = manifest(payloads)
        assert data.count == 129 and len(data.pages) == 2
        assert (
            begin(
                writer,
                2,
                102,
                202,
                scope="account_v1",
                count=data.count,
                root=data.root,
            )
            == "staging"
        )
        acknowledge_header(checkpoint)
        deny(
            writer,
            "SELECT retirement.append_page(%s,%s,%s,%s,%s)",
            (INSTALLATION, identifier(2), 1, INITIAL, list(data.pages[1])),
            state="23514",
        )
        previous = INITIAL
        for index, entries in enumerate(data.pages):
            args = (INSTALLATION, identifier(2), index, previous, list(entries))
            value = writer.execute(
                "SELECT retirement.append_page(%s,%s,%s,%s,%s)", args
            ).fetchone()[0]
            assert value == page_digest(previous, index, entries)
            assert (
                writer.execute(
                    "SELECT retirement.append_page(%s,%s,%s,%s,%s)", args
                ).fetchone()[0]
                == value
            )
            changed = list(entries)
            changed[0] = changed[0][:-1] + bytes([changed[0][-1] ^ 1])
            deny(
                writer,
                "SELECT retirement.append_page(%s,%s,%s,%s,%s)",
                (INSTALLATION, identifier(2), index, previous, changed),
                state="23514",
            )
            previous = value
        passed("two_bounded_pages_real_codec_exact_replay_and_changed_page_denial")
        second = seal(writer, 2)
        acknowledge(checkpoint, *second)
        try:
            begin(writer, 2, 102, 202, scope="account_v1", count=1, root=data.root)
        except psycopg.Error as error:
            assert error.sqlstate == "23514"
        else:
            raise AssertionError("restored_missing_manifest_recomputed_smaller_root")
        passed("missing_original_manifest_cannot_be_replaced_with_smaller_count")
        candidates = KEY.google_grant_candidates(
            ISSUER, "SyntheticSubject0", "fresh@example.test"
        )
        decision = writer.execute(
            "SELECT retired FROM retirement.check_google_grant(%s,%s,%s,%s,%s)",
            (INSTALLATION, DATASET, KEY_ID, candidates[0].digest, candidates[1].digest),
        ).fetchone()
        assert decision == (True,)
        candidates = KEY.google_grant_candidates(
            ISSUER, "FreshSubject", "owner@example.test"
        )
        assert writer.execute(
            "SELECT retired FROM retirement.check_google_grant(%s,%s,%s,%s,%s)",
            (INSTALLATION, DATASET, KEY_ID, candidates[0].digest, candidates[1].digest),
        ).fetchone() == (True,)
        passed("subject_and_mailbox_retirement_independent_of_reenrollment_UUID")
        try:
            begin(
                writer,
                4,
                102,
                204,
                scope="account_v1",
                floor=3,
                count=1,
                root=data.root,
            )
        except psycopg.Error as error:
            assert error.sqlstate == "23514"
        else:
            raise AssertionError("closed_owner_reopened")
        assert begin(writer, 3, 101, 203, floor=3) == "staging"
        acknowledge_header(checkpoint)
        third = seal(writer, 3)
        acknowledge(checkpoint, *third)
        assert begin(writer, 1, 101, 201) == "sealed"
        original = writer.execute(
            "SELECT job_id,created_at,history_floor FROM retirement.lookup_intent(%s)",
            (identifier(1),),
        ).fetchone()
        assert (str(original[0]), original[1], original[2]) == (
            identifier(201),
            CREATED,
            2,
        )
        passed("later_generation_does_not_retarget_old_intent_or_reopen_closed_owner")
        values = recovery.execute(
            "SELECT last_sequence,pending_count,intent_count,owner_count,fingerprint_count,reserved_fingerprints FROM retirement.checkpoint()"
        ).fetchone()
        assert values == (3, 0, 3, 2, 129, 0)
        passed("exact_metadata_counts_and_reservations")


def commit_failure():
    # Explicit fake FS seam: this case proves Broker's actual PostgreSQL COMMIT
    # error handling, not storage completeness or publication. No grants occur.
    protected = object.__new__(ProtectedFile)
    protected.require_current = lambda conn, **kwargs: None
    with ConnectionPool(
        dsn("aqua_retirement_writer"),
        min_size=0,
        max_size=1,
        kwargs={"autocommit": True, "connect_timeout": 3},
        timeout=1,
    ) as pool:
        broker = Broker(pool, INSTALLATION, key=KEY, checkpoint=protected)
        returned = False
        try:

            def apply(conn):
                value = begin(conn, 4, 103, 204)
                conn.execute("SET LOCAL synchronous_commit='off'")
                return value

            broker.authority_transaction(apply)
            returned = True
        except RetirementUnavailable:
            pass
        assert returned is False
    with connect("aqua_retirement_recovery") as reader:
        assert reader.execute(
            "SELECT last_sequence,pending_count FROM retirement.checkpoint()"
        ).fetchone() == (3, 0)
    passed("actual_deferred_COMMIT_failure_never_returns_header_or_ack")


def finish_fault():
    with (
        connect("aqua_retirement_writer") as writer,
        connect("aqua_retirement_checkpoint") as cp,
    ):
        begin(writer, 4, 103, 204)
        acknowledge_header(cp)
        acknowledge(cp, *seal(writer, 4))
    passed("same_pending_intent_recovers_after_injected_COMMIT_failure")


def reconcile():
    with connect("aqua_retirement_writer") as writer:
        row = writer.execute(
            "SELECT owner_id,job_id,created_at,scope,history_floor,privacy_floor,auth_floor,account_closed,sequence,event_digest,checkpointed_at FROM retirement.lookup_intent(%s)",
            (identifier(1),),
        ).fetchone()
    (
        owner,
        job,
        created,
        scope,
        history,
        privacy,
        auth,
        closed,
        sequence,
        digest,
        checkpointed,
    ) = row
    intent = Intent(
        INSTALLATION,
        str(owner),
        identifier(1),
        str(job),
        scope,
        created,
        history,
        privacy,
        auth,
        closed,
        sequence,
        digest,
        checkpointed,
    )
    with connect("aqua_app_runtime", database="aqua_app") as app:
        with app.transaction():
            first = reconcile_tombstone(app, intent)
            second = reconcile_tombstone(app, intent)
            assert first == second and first.history_floor == 2
            assert first.job == identifier(201) and first.created_at == CREATED
            assert first.cleanup_complete is False
            assert first.acceptance_confirmed is True and first.updated_at == CREATED
        deny(app, "DELETE FROM app.retirement_intents", state="42501")
        deny(app, "TRUNCATE app.retirement_intents", state="42501")
        deny(
            app,
            "UPDATE app.retirement_intents SET history_floor=history_floor+1",
            state="23514",
        )
        deny(
            app,
            "UPDATE app.retirement_intents SET job_id=%s",
            (identifier(999),),
            state="23514",
        )
    passed("actual_reconciliation_retains_original_job_time_floor_and_immutable_ack")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) == 2 else "invalid"
    assert mode in {"suite", "commit-failure", "finish-fault", "reconcile"}
    {
        "suite": suite,
        "commit-failure": commit_failure,
        "finish-fault": finish_fault,
        "reconcile": reconcile,
    }[mode]()
    print(
        json.dumps(
            {
                "status": "passed",
                "mode": mode,
                "checks": RESULTS,
                "protected_checkpoint_storage_proven": False,
                "application_deletion_paths_proven": False,
            }
        )
    )
