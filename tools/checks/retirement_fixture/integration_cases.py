"""Current two-DB composition, only inside an owned socket-only test fixture.

Uses the actual AuthorityClient, Broker, independent SQL and Ed25519 publisher.
Only unsupported append-only inode provisioning and the separate physical mail
mount are explicit seams; this does not assert production storage activation.
"""

from contextlib import nullcontext
from dataclasses import replace
import json
import hashlib
import os
from pathlib import Path
import sys

import psycopg
import pytest
from psycopg_pool import ConnectionPool
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from auth.sessions import new_token, token_digest, session_cookie_name
from auth.store import IdentityStore
from auth.mailconfig import MailPolicy
from auth.mailqueue import MailOutbox
from auth.mailworker import MailWorker
from privacy.deletion_service import Deletions
from privacy.deletion_worker import Worker
from retirement import checkpoint
from retirement.client import AuthorityClient, ConfirmedRetirement
from retirement.fingerprints import IdentityKey, ISSUER
from retirement.interlock import Broker, RetirementUnavailable
from retirement.publisher import HostPublisher, signed_record
from retirement.recovery import reconcile
from retirement.runtime import Runtime
from retirement.startup import validate
from storage.config import StorageSettings
from storage.migrate import apply
from storage.pool import Storage, StorageUnavailable
from workspace_fixtures import World
from identity_action_fixtures import IdentityWorld
from test_deletion_lifecycle import request, status, settle
import native_support

INSTALLATION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
KEY_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
KEY = IdentityKey(KEY_ID, b"synthetic-fixture-HMAC-key-only!".ljust(32, b"0"))
CHECKS = []


def denied(conn, statement, values=()):
    try:
        with conn.transaction():
            conn.execute(statement, values)
    except psycopg.Error as error:
        assert error.sqlstate == "42501"
    else:
        raise AssertionError("independent_role_privilege_denial_missing")


def dsn(role, database="aqua_retirement"):
    if role not in {
        "aqua_retirement_writer",
        "aqua_retirement_checkpoint",
        "aqua_retirement_recovery",
        "aqua_app_runtime",
        "aqua_app_migrator",
    } or database not in {"aqua_app", "aqua_retirement"}:
        raise AssertionError("fixture_connection_scope_invalid")
    password = (
        native_support.AUTH_PASSWORD
        if native_support.enabled() and role.startswith("aqua_retirement_")
        else "fixture-only"
    )
    return f"host=/run/aqua-app-db port=5432 dbname={database} user={role} password={password} sslmode=disable"


def sync(stage):
    print(stage, flush=True)
    if sys.stdin.readline().strip() != "continue":
        raise AssertionError("fixture_orchestration_invalid")


def main():
    import main as application

    seed_value = os.environ.get("AQUA_RETIREMENT_NORMAL_SEED", "false")
    if (
        seed_value not in {"true", "false"}
        or seed_value == "true"
        and not native_support.enabled()
    ):
        raise RuntimeError("normal_seed_owned_native_mode_required")
    normal_seed = seed_value == "true"

    monkeypatch = pytest.MonkeyPatch()
    writer = ConnectionPool(
        dsn("aqua_retirement_writer"),
        min_size=0,
        max_size=1,
        timeout=1,
        kwargs={"autocommit": True, "prepare_threshold": None, "connect_timeout": 2},
    )
    host = ConnectionPool(
        dsn("aqua_retirement_checkpoint"),
        min_size=0,
        max_size=1,
        timeout=1,
        kwargs={"autocommit": True, "prepare_threshold": None, "connect_timeout": 2},
    )
    storage = Storage(
        StorageSettings(True, dsn("aqua_app_runtime", "aqua_app"), 1, 1, 1)
    )
    service = None
    try:
        with psycopg.connect(
            dsn("aqua_app_migrator", "aqua_app"), autocommit=True, connect_timeout=2
        ) as conn:
            assert apply(conn) == 9
        # An older app-only backup can predate the one-way installed marker.
        # The independent database catalog still makes a real host claim
        # mandatory on this same single app connection, even with no flag.
        with storage.transaction() as conn:
            assert conn.execute(
                "SELECT authority_installed FROM app.retirement_control"
            ).fetchone() == (False,)

        class NeverTransport:
            def send(self, *args):
                raise AssertionError("installed_catalog_reached_unprotected_transport")

        try:
            MailWorker(
                MailOutbox(
                    storage, MailPolicy(True, b"m" * 32, "https://mail.fixture")
                ),
                NeverTransport(),
            ).once()
        except StorageUnavailable:
            pass
        else:
            raise AssertionError(
                "old_app_marker_bypassed_independent_catalog_mail_guard"
            )
        try:
            Runtime(storage).start()
        except RetirementUnavailable:
            pass
        else:
            raise AssertionError(
                "installed_catalog_opened_web_without_authority_configuration"
            )
        CHECKS.append(
            "independent_catalog_survives_old_app_marker_and_denies_flagless_mail_or_missing_web_config"
        )
        with writer.connection() as conn:
            assert conn.execute(
                "SELECT rolsuper,rolinherit,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolconnlimit FROM pg_roles WHERE rolname=current_user"
            ).fetchone() == (False, False, False, False, False, False, 1)
            for sql in (
                "SELECT * FROM retirement.control",
                "DELETE FROM retirement.intents",
                "TRUNCATE retirement.journal",
                "CREATE TABLE retirement.forbidden(x int)",
                "CREATE TEMP TABLE forbidden(x int)",
                "SET ROLE aqua_retirement_owner",
                "SELECT * FROM retirement.read_events(0,1)",
                "SELECT retirement.acknowledge_checkpoint('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',0,decode(repeat('00',32),'hex'))",
            ):
                denied(conn, sql)
            assert conn.execute(
                "SELECT has_database_privilege('aqua_app_runtime','aqua_retirement','CONNECT')"
            ).fetchone() == (False,)
        with host.connection() as conn:
            denied(conn, "SELECT retirement.writer_guard()")
        if native_support.enabled():
            # A separate publisher needs the checkpoint role's sole slot.
            # Physically close this now-unused privilege-check connection.
            host.close(timeout=3)
        with psycopg.connect(
            dsn("aqua_retirement_recovery"), autocommit=True, connect_timeout=2
        ) as conn:
            denied(conn, "SELECT * FROM retirement.control")
            denied(conn, "SELECT retirement.writer_guard()")
            assert conn.execute("SHOW default_transaction_read_only").fetchone() == (
                "on",
            )
        CHECKS.append(
            "actual_independent_roles_no_table_DML_DDL_escalation_or_cross_DB_app_access"
        )
        native = native_support.enabled()
        directory = (
            native_support.AUTHORITY if native else Path("/tmp/retirement-composition")
        )
        if not native:
            directory.mkdir(mode=0o700)
        path = directory / "checkpoints.bin"
        private = (
            Ed25519PrivateKey.from_private_bytes(native_support.SEED)
            if native
            else Ed25519PrivateKey.generate()
        )
        public = private.public_key().public_bytes_raw()
        genesis = signed_record(
            private,
            installation=INSTALLATION,
            key_id=KEY_ID,
            sequence=0,
            digest=bytes(32),
            previous=bytes(32),
            commitment=KEY.commitment,
        )
        if native:
            assert path.read_bytes() == genesis
        else:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                assert os.write(fd, genesis) == 208
                os.fsync(fd)
            finally:
                os.close(fd)
        # This single named seam is necessary in an unprivileged tmpfs fixture.
        # Real signature verification, inode/mode checks, writes and fsync run.
        if not native:
            monkeypatch.setattr(checkpoint, "append_only", lambda fd: True)
        protected = checkpoint.ProtectedFile(
            path,
            owner_uid=1000,
            public_key=public,
            installation=INSTALLATION,
            key_id=KEY_ID,
            commitment=KEY.commitment,
        )
        publisher = (
            native_support.Publisher(protected)
            if native
            else HostPublisher(host, protected, private)
        )
        publisher.startup()
        publisher.once()
        authority = AuthorityClient(
            Broker(writer, INSTALLATION, key=KEY, checkpoint=protected)
        )
        runtime = Runtime(storage, client=authority, enabled=True)
        validate(storage, authority, authority.startup_checkpoint())
        runtime.ready = True
        if not native:
            monkeypatch.setattr(
                runtime, "purge_guard", lambda closed: nullcontext(True)
            )
        else:
            from retirement.mail_physical import validate as validate_mail_mount

            validate_mail_mount()
        monkeypatch.setattr(storage, "retirement", runtime, raising=False)
        world = World(storage, monkeypatch)
        secure = IdentityWorld(world, monkeypatch)
        world.analysis.settings = world.settings
        client, owner = secure.client(linked=True)
        with storage.transaction() as conn:
            conn.execute(
                "INSERT INTO app.dataset_grants(user_id,dataset_key) VALUES(%s,%s)",
                (owner, world.policy.dataset_key),
            )
        service = Deletions(storage, world.policy, world.settings, runtime)
        monkeypatch.setattr(application.app.state, "deletions", service, raising=False)
        worker = Worker(service)
        world.submit(client, "Synthetic old answer for app-only restore")
        sync("READY_FOR_BACKUP")
        body = request(secure, client, owner)
        pending = client.post("/api/v1/me/data-deletions", json=body)
        assert pending.status_code == 503, pending.text
        original_pending = status(client, body).json()
        assert original_pending["job"]["accepted"] is False
        with storage.transaction() as conn:
            assert conn.execute("SELECT count(*) FROM app.chats").fetchone() == (1,)
        try:
            worker.once()
        except RetirementUnavailable:
            pass
        else:
            raise AssertionError("unpublished_header_allowed_worker")
        if native:
            before_retry = publisher.crash_before_ack()
            unacknowledged = status(client, body)
            assert unacknowledged.status_code == 200, unacknowledged.text
            native_support.pending_receipt(original_pending, unacknowledged.json())
            try:
                worker.once()
            except RetirementUnavailable:
                pass
            else:
                raise AssertionError("uncommitted_checkpoint_ack_allowed_purge")
            with storage.transaction() as conn:
                assert conn.execute("SELECT count(*) FROM app.chats").fetchone() == (1,)
            publisher.once()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == before_retry
            CHECKS.append(
                "actual_fsync_before_ACK_backend_death_retry_identical_bytes_no_extra_append"
            )
        else:
            publisher.once()
        accepted = status(client, body)
        assert accepted.status_code == 200 and accepted.json()["job"]["accepted"]
        assert client.post("/api/v1/me/data-deletions", json=body).status_code == 200
        settle(worker)
        assert (
            type(authority.confirm(owner, body["intent_id"], body["scope"]))
            is ConfirmedRetirement
        )
        assert status(client, body).json()["job"]["cleanup_complete"]
        CHECKS.append(
            "history_actual_SQL_signed_publisher_pending_reconcile_seal_purge"
        )
        client.headers["X-Aqua-History-Revision"] = accepted.json()["history_revision"]
        world.submit(client, "Synthetic current answer before account close")
        original_prepare = authority.prepare

        def publish_after_prepare(*args):
            result = original_prepare(*args)
            publisher.once()
            return result

        monkeypatch.setattr(authority, "prepare", publish_after_prepare)
        account = request(secure, client, owner, "account_v1")
        response = client.post("/api/v1/me/data-deletions", json=account)
        assert response.status_code == 202, response.text
        assert client.get("/api/v1/chats").status_code == 401
        assert status(client, account).json()["job"]["accepted"]
        if normal_seed:
            payload = {
                "session_token": client.cookies.get(
                    session_cookie_name(world.settings)
                ),
                "csrf_token": client.headers["X-CSRF-Token"],
                "receipt_token": account["receipt_token"],
                "intent_id": account["intent_id"],
                "job_id": response.json()["job"]["id"],
                "owner_id": owner,
            }
            raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            if len(raw) > 8192:
                raise RuntimeError("normal_seed_private_frame_capacity")
            sys.stdout.buffer.write(
                b"NORMAL_RECEIPT " + str(len(raw)).encode() + b"\n" + raw
            )
            sys.stdout.buffer.flush()
            return
        settle(worker)
        assert status(client, account).json()["job"]["cleanup_complete"]
        with storage.transaction() as conn:
            assert conn.execute(
                "SELECT count(*) FROM app.users WHERE id=%s", (owner,)
            ).fetchone() == (0,)
            assert conn.execute(
                "SELECT count(*) FROM app.retirement_intents"
            ).fetchone() == (2,)
        CHECKS.append(
            "account_HTTP202_actual_SQL_complete_fingerprint_seal_and_bounded_purge"
        )
        policy = replace(
            world.policy,
            allowed_google_subs=frozenset({"workspace-A"}),
            allowed_emails=frozenset({"a@gmail.com"}),
        )
        store = IdentityStore(storage, policy)
        identity = {
            "iss": ISSUER,
            "sub": "workspace-A",
            "email": "a@gmail.com",
            "email_verified": True,
        }
        fresh = store.login(
            identity,
            token_digest(new_token()),
            b"c" * 32,
            "fixture-peer",
            world.settings,
        )
        assert fresh.user["id"] != owner and fresh.can_query is False
        candidates = KEY.google_grant_candidates(ISSUER, "other-subject", "a@gmail.com")
        decision = authority.grant_transaction(
            storage, "d" * 64, candidates, lambda conn, decision: decision
        )
        assert decision.retired is True
        CHECKS.append(
            "new_UUID_legacy_subject_mailbox_and_future_dataset_grants_denied"
        )
        sync("READY_FOR_RESTORE")
        head = authority.startup_checkpoint()
        try:
            validate(storage, authority, head)
        except RetirementUnavailable:
            pass
        else:
            raise AssertionError(
                "app_only_restore_opened_writers_without_reconciliation"
            )
        with psycopg.connect(
            dsn("aqua_retirement_recovery"), autocommit=True, connect_timeout=2
        ) as conn:
            result = reconcile(
                storage, conn, protected, purge_guard=runtime.purge_guard
            )
        assert result.ready and result.events_verified == 2
        validate(storage, authority, head)
        with storage.transaction() as conn:
            assert conn.execute(
                "SELECT count(*) FROM app.users WHERE id=%s", (owner,)
            ).fetchone() == (0,)
            assert conn.execute("SELECT count(*) FROM app.chats").fetchone() == (0,)
            assert conn.execute(
                "SELECT count(*) FROM app.retirement_intents"
            ).fetchone() == (2,)
        assert client.get("/api/v1/chats").status_code == 401
        assert status(client, account).status_code == 404
        after = store.login(
            identity,
            token_digest(new_token()),
            b"d" * 32,
            "fixture-peer",
            world.settings,
        )
        assert after.user["id"] != owner and after.can_query is False
        CHECKS.append(
            "actual_app_dump_restore_signed_events_pages_recovery_no_resurrection_or_legacy_grant"
        )
        if native:
            native_support.sync("NATIVE_POISON")
            monkeypatch.setattr(protected, "path", directory / "poison.bin")
        else:
            raw = path.read_bytes()
            path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        try:
            authority.confirm_acceptance(owner, account["intent_id"], account["scope"])
        except RetirementUnavailable:
            pass
        else:
            raise AssertionError("tampered_checkpoint_allowed_acceptance")
        CHECKS.append(
            "actual_poisoned_checkpoint_tail_denies_acceptance"
            if native
            else "real_Ed25519_signature_tamper_denies_acceptance"
        )
        print(
            json.dumps(
                {
                    "status": "passed",
                    "checks": CHECKS,
                    "independent_transport": "private_unix_socket",
                    "synthetic_authority": False,
                    "append_only_inode_storage_proven": native,
                    "physical_mail_mount_proven": native,
                    "physical_mail_sender_lifetime_proven": False,
                }
            ),
            flush=True,
        )
    finally:
        if service is not None:
            service.close()
        storage.close()
        writer.close()
        host.close()
        monkeypatch.undo()


if __name__ == "__main__":
    main()
