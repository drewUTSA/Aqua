"""Actual offline retained-authority repair, then a synthetic login actor.

This is separate from the ordinary Uvicorn runtime proof. No signing seed or
operator credential is mounted; the native fixture's public recovery credential
is fixed in source and works only against its owned socket namespace.
"""

import argparse
import json
import os
import signal
import sys


def execute(value):
    if (
        os.geteuid() != 1000
        or sys.platform != "linux"
        or os.environ.get("AQUA_RETIREMENT_NATIVE_FIXTURE") != "true"
    ):
        raise RuntimeError("normal_recovery_owned_fixture_required")
    import psycopg
    from auth.config import load_auth_policy
    from auth.sessions import new_token, token_digest, bound_value
    from auth.store import IdentityStore
    from nl2sql.config import settings_from
    from retirement.client import AuthorityClient
    from retirement.checkpoint import ProtectedFile
    from retirement.interlock import Broker
    from retirement.runtime import Runtime, _pool
    from retirement.settings import load, DIRECTORY
    from retirement.mail_physical import gate
    from storage.config import StorageSettings
    from storage.pool import Storage
    from ops.retirement.recovery_driver import app_only
    from normal_runtime_probe import ENV, checked
    from native_support import AUTH_PASSWORD
    from contextlib import nullcontext

    if type(value) is not dict or set(value) != {"request", "protected_sha256"}:
        raise RuntimeError("normal_recovery_input_closed")
    request = checked(value["request"])
    configured = load()
    if configured is None:
        raise RuntimeError("normal_recovery_retained_configuration_missing")
    protected = ProtectedFile(
        DIRECTORY / "checkpoints.bin",
        owner_uid=1000,
        public_key=configured.public_key,
        installation=configured.installation,
        key_id=configured.identity.key_id,
        commitment=configured.identity.commitment,
    )
    storage = Storage(StorageSettings(True, ENV["APP_DATABASE_URL"], 4, 8, 2))
    storage.open()
    pool = None
    try:
        with psycopg.connect(
            "host=/run/aqua-app-db port=5432 dbname=aqua_retirement user=aqua_retirement_recovery password="
            + AUTH_PASSWORD
            + " sslmode=disable",
            autocommit=True,
            connect_timeout=2,
        ) as conn:
            # Transfer the fixture prep timer to the unchanged operator API;
            # the host role channel keeps its original absolute60s bound.
            signal.alarm(0)
            result = app_only(
                storage,
                conn,
                protected,
                expected_protected_sha256=value["protected_sha256"],
                purge_guard=lambda closed: gate() if closed else nullcontext(True),
                batch_limit=128,
            )
        if (
            result["ready"] is not True
            or result["events_verified"] != 2
            or result["pending_manifest"] is not False
        ):
            raise RuntimeError("normal_recovery_complete_history_unproven")
        with storage.transaction() as conn:
            if conn.execute(
                "SELECT count(*) FROM app.users WHERE id=%s", (request["owner_id"],)
            ).fetchone() != (0,):
                raise RuntimeError("normal_recovery_closed_owner_resurrected")
            if conn.execute("SELECT count(*) FROM app.chats").fetchone() != (0,):
                raise RuntimeError("normal_recovery_old_chat_resurrected")
        # Setup actor uses the exact production Runtime.start and grant commit
        # gate, distinct from the separately spawned normal Runtime.create web.
        pool = _pool(configured)
        pool.open(wait=False)
        authority = AuthorityClient(
            Broker(
                pool,
                configured.installation,
                key=configured.identity,
                checkpoint=protected,
            )
        )
        runtime = Runtime(storage, client=authority, enabled=False)
        storage.retirement = runtime
        runtime.start()
        settings = settings_from(ENV)
        policy = load_auth_policy(settings)
        token = new_token()
        csrf = bound_value(settings, token, "session-csrf")
        session = IdentityStore(storage, policy).login(
            {
                "iss": "https://accounts.google.com",
                "sub": "workspace-A",
                "email": "a@gmail.com",
                "email_verified": True,
            },
            token_digest(token),
            token_digest(csrf),
            "fixture-peer",
            settings,
        )
        if session.user["id"] == request["owner_id"] or session.can_query is not False:
            raise RuntimeError("normal_recovery_legacy_grant_revived")
        with storage.transaction() as conn:
            if conn.execute(
                "SELECT count(*) FROM app.dataset_grants WHERE user_id=%s",
                (session.user["id"],),
            ).fetchone() != (0,):
                raise RuntimeError("normal_recovery_new_UUID_has_legacy_grant")
        payload = {
            **request,
            "mode": "ready",
            "owner_id": session.user["id"],
            "session_token": token,
            "csrf_token": csrf,
        }
        public = {
            "status": "passed",
            "offline_recovery": result,
            "new_UUID_distinct": True,
            "new_UUID_legacy_grants": 0,
            "setup_actor_normal_factory_claimed": False,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        print(json.dumps(public, sort_keys=True), flush=True)
        sys.stdout.buffer.write(
            b"NORMAL_REPAIRED " + str(len(raw)).encode() + b"\n" + raw
        )
        sys.stdout.buffer.flush()
    finally:
        if pool is not None:
            pool.close(timeout=3)
        storage.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "prepared_only",
                    "private_reads": 0,
                    "pool_opens": 0,
                    "writes": 0,
                }
            )
        )
        return
    signal.alarm(60)
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536:
        raise RuntimeError("normal_recovery_input_capacity")
    execute(json.loads(raw))


if __name__ == "__main__":
    main()
