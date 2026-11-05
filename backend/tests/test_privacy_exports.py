"""Proof-target, ownership, physical lease, privacy and current-grant fences."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import hashlib
import json
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest

from account.policy import target_digest
from auth.admission import cleanup
from privacy import policy, records
from privacy.contracts import ExportCreate
from privacy.cursors import Cursors
from privacy.database import WORKER_LOCK, global_lock
from privacy.service import ExportService
from privacy.worker import Worker
from storage.pool import Storage
from workspace.errors import WorkspaceError
from privacy_export_fixture import EXPORTS


def spent(fixture, proof):
    from auth.sessions import token_digest

    with fixture.world.storage.transaction() as conn:
        return conn.execute(
            "SELECT consumed_at IS NOT NULL FROM app.account_action_proofs WHERE secret_digest=%s",
            (token_digest(proof),),
        ).fetchone()[0]


def test_export_intent_and_scope_have_a_separate_proof_target():
    intent = str(uuid4())
    assert target_digest("data_export", intent) == policy.target_digest(intent)
    assert target_digest("data_export", intent) != target_digest(
        "session_revoke", intent
    )
    assert target_digest("data_export", intent) != policy.target_digest(str(uuid4()))
    assert (
        target_digest("sessions_revoke_all")
        == hashlib.sha256(
            b'["aqua-account-action-v1","sessions_revoke_all",null]'
        ).digest()
    )


def test_export_consumption_and_job_are_atomic_and_same_intent_is_idempotent(
    private_exports,
):
    fixture = private_exports
    client, owner = fixture.client()
    job, body = fixture.queue(client)
    assert spent(fixture, body["proof_token"])
    again = client.post(EXPORTS, json=body)
    assert again.status_code == 200, again.text
    assert again.json()["job"]["id"] == job["id"]
    with fixture.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*),sum(reserved_bytes) FROM app.data_exports WHERE user_id=%s",
            (owner,),
        ).fetchone() == (1, policy.MAX_EXPORT_BYTES)
        assert conn.execute(
            "SELECT reserved_bytes,stored_bytes FROM app.privacy_control WHERE singleton"
        ).fetchone() == (policy.MAX_EXPORT_BYTES, 0)
    rebound = client.post(EXPORTS, json={**body, "intent_id": str(uuid4())})
    assert rebound.status_code == 429
    reconciled = client.get(EXPORTS + "/by-intent/" + job["intent_id"])
    assert reconciled.status_code == 200
    assert reconciled.json()["job"] == again.json()["job"]


def test_wrong_intent_cannot_consume_fresh_export_proof(private_exports):
    fixture = private_exports
    client, _ = fixture.client()
    intent = str(uuid4())
    proof = fixture.proof(client, intent)
    bad = client.post(
        EXPORTS,
        json={"intent_id": str(uuid4()), "scope": "personal_v1", "proof_token": proof},
    )
    assert bad.status_code == 403, bad.text
    assert not spent(fixture, proof)
    good = client.post(
        EXPORTS,
        json={"intent_id": intent, "scope": "personal_v1", "proof_token": proof},
    )
    assert good.status_code == 202, good.text


def test_concurrent_creation_replays_one_intent_and_reserves_once(private_exports):
    fixture = private_exports
    client, owner = fixture.client()
    intent = str(uuid4())
    proof = fixture.proof(client, intent)
    body = ExportCreate(intent_id=intent, scope="personal_v1", proof_token=proof)
    session = fixture.secure.principal(client)
    pools = [Storage(fixture.world.storage.settings) for _ in range(2)]
    services = [
        ExportService(pool, fixture.world.policy, fixture.world.settings)
        for pool in pools
    ]
    barrier = Barrier(2)

    def create(service):
        barrier.wait(timeout=3)
        return service.create(session, body, fixture.secure.passwords)

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(create, services))
        assert sorted(status for _, status in results) == [200, 202]
        assert len({result["job"]["id"] for result, _ in results}) == 1
        with fixture.world.storage.transaction() as conn:
            assert conn.execute(
                "SELECT count(*) FROM app.data_exports WHERE user_id=%s", (owner,)
            ).fetchone() == (1,)
            assert conn.execute(
                "SELECT reserved_bytes FROM app.privacy_control WHERE singleton"
            ).fetchone() == (policy.MAX_EXPORT_BYTES,)
    finally:
        import anyio

        for service in services:
            anyio.run(service.aclose)
        for pool in pools:
            pool.close()


@pytest.mark.parametrize("google", [False, True])
def test_export_without_dataset_grant_or_mail_includes_only_owned_json(
    private_exports, monkeypatch, google
):
    fixture = private_exports
    client, owner = fixture.client(linked=not google)
    monkeypatch.setenv("ACCOUNT_MAIL_ENABLED", "false")
    foreign, _ = fixture.client("B")
    hidden = foreign.post(
        "/api/v1/projects",
        json={"client_request_id": str(uuid4()), "name": "FOREIGN-EXPORT-CANARY"},
    )
    assert hidden.status_code == 201, hidden.text
    ready, raw, _ = fixture.ready(client, owner, google=google)
    payload = json.loads(raw)
    assert set(payload) == {
        "schemaVersion",
        "scope",
        "export",
        "profile",
        "preferences",
        "notification_settings",
        "projects",
        "saved_prompts",
        "chats",
        "messages",
    }
    assert payload["profile"]["display_name"] == "A"
    for canary in (
        b"FOREIGN-EXPORT-CANARY",
        b"synthetic-account-hash",
        b"workspace-A",
        b"csrf_digest",
        b"token_digest",
        b"approval_evidence",
        b"session_secret",
        b"proof_token",
    ):
        assert canary not in raw
    assert datetime.fromisoformat(ready["expires_at"]) - datetime.fromisoformat(
        ready["created_at"]
    ) == timedelta(hours=1)
    assert fixture.world.calls == []
    assert len(fixture.secure.provider_calls) == int(google)
    other = foreign.get(EXPORTS + "/" + ready["id"])
    assert other.status_code == 404
    assert foreign.get(EXPORTS + "/by-intent/" + ready["intent_id"]).status_code == 404


def test_current_grant_is_checked_at_snapshot_and_publish(private_exports):
    fixture = private_exports
    client, owner = fixture.client(grant=True)
    completed = fixture.world.submit(client)
    job, _ = fixture.queue(client)

    def revoke():
        with fixture.world.storage.transaction() as conn:
            conn.execute(
                "UPDATE app.dataset_grants SET revoked_at=clock_timestamp(),version=version+1 WHERE user_id=%s",
                (owner,),
            )

    fixture.service.after_capture = revoke
    assert fixture.worker.once()
    status = client.get(EXPORTS + "/" + job["id"]).json()["job"]
    assert status["state"] == "failed"
    assert status["error_code"] == "authority_changed"
    assert "byte_count" not in status and "sha256" not in status
    assert fixture.bytes(owner, job["id"]) == b""
    assert completed["request"]["state"] == "complete"
    assert len(fixture.world.calls) == 1


@pytest.mark.parametrize(
    "change", ["session", "auth_epoch", "privacy_epoch", "disabled", "regrant"]
)
def test_changes_after_snapshot_cannot_publish_any_staged_bytes(
    private_exports, change
):
    fixture = private_exports
    client, owner = fixture.client(grant=True)
    fixture.world.submit(client)
    job, _ = fixture.queue(client)

    def change_authority():
        assert fixture.bytes(owner, job["id"])
        with fixture.world.storage.transaction() as conn:
            if change == "session":
                conn.execute(
                    "UPDATE app.sessions SET revoked_at=clock_timestamp() WHERE user_id=%s",
                    (owner,),
                )
            elif change == "disabled":
                conn.execute(
                    "UPDATE app.users SET status='disabled' WHERE id=%s", (owner,)
                )
            elif change == "regrant":
                conn.execute(
                    "UPDATE app.dataset_grants SET version=version+2 WHERE user_id=%s",
                    (owner,),
                )
            else:
                field = "auth_epoch" if change == "auth_epoch" else "privacy_epoch"
                conn.execute(
                    "UPDATE app.users SET " + field + "=" + field + "+1 WHERE id=%s",
                    (owner,),
                )

    fixture.service.after_capture = change_authority
    assert fixture.worker.once()
    assert fixture.bytes(owner, job["id"]) == b""
    with fixture.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT state,error_code FROM app.data_exports WHERE id=%s", (job["id"],)
        ).fetchone() == ("failed", "authority_changed")
        assert conn.execute(
            "SELECT reserved_bytes,stored_bytes FROM app.privacy_control WHERE singleton"
        ).fetchone() == (0, 0)


def test_owned_result_number_tokens_remain_exact_and_private_root_fields_are_excluded(
    private_exports,
):
    fixture = private_exports
    client, owner = fixture.client(grant=True)
    completed = fixture.world.submit(client)
    exact = "9007199254740993.12345678901234567890123456789"
    with fixture.world.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.visual_results SET response=jsonb_set(response,'{tables,0,rows,0,value}',%s::jsonb) || jsonb_build_object('provider_internal','PRIVATE-PROVIDER-CANARY') WHERE user_id=%s AND request_id=%s",
            (exact, owner, completed["request"]["id"]),
        )
    _, raw, _ = fixture.ready(client, owner)
    result = next(
        item["response"]
        for item in json.loads(raw, parse_float=Decimal)["messages"]
        if item["role"] == "aqua"
    )
    assert result["tables"][0]["rows"][0]["value"] == Decimal(exact)
    assert exact.encode() in raw
    assert b"PRIVATE-PROVIDER-CANARY" not in raw


def test_json_escaping_over_output_cap_rolls_back_instead_of_truncating(
    private_exports,
):
    fixture = private_exports
    client, owner = fixture.client()
    with fixture.world.storage.transaction() as conn:
        # 6MB source content fits the existing 16MiB owner bound; valid JSON
        # escaping expands it beyond the independent 32MiB output cap. Each
        # chat/message/request still satisfies its existing row/owner FK bounds.
        conn.execute(
            "INSERT INTO app.chats(id,user_id,title,next_message_sequence,message_count) SELECT md5(%s||'chat'||i::text)::uuid,%s,'Bounded source',201,200 FROM generate_series(0,29) i",
            (owner, owner),
        )
    # Keep every synthetic statement/commit inside the unchanged three-second
    # SQL bound. A batch contains complete deferred-FK message/request groups.
    for first in range(1, 3001, 100):
        last = first + 99
        with fixture.world.storage.transaction() as conn:
            conn.execute(
                "INSERT INTO app.messages(id,user_id,chat_id,sequence,role,content,request_id,reply_to,model_id,status) SELECT md5(%s||'input'||i::text)::uuid,%s::uuid,md5(%s||'chat'||((i-1)/100)::text)::uuid,((i-1)%%100)*2+1,'user',repeat(chr(1),2000),md5(%s||'request'||i::text)::uuid,NULL,'ollama','complete' FROM generate_series(%s::integer,%s::integer) i UNION ALL SELECT md5(%s||'reply'||i::text)::uuid,%s::uuid,md5(%s||'chat'||((i-1)/100)::text)::uuid,((i-1)%%100)*2+2,'aqua','',md5(%s||'request'||i::text)::uuid,md5(%s||'input'||i::text)::uuid,'ollama','complete' FROM generate_series(%s::integer,%s::integer) i",
                (owner,) * 4 + (first, last) + (owner,) * 5 + (first, last),
            )
            conn.execute(
                "INSERT INTO app.analysis_requests(id,user_id,chat_id,client_request_id,fingerprint,input_message_id,reply_message_id,state,reserved_bytes,requested_model,dataset_key,grant_version) SELECT md5(%s||'request'||i::text)::uuid,%s,md5(%s||'chat'||((i-1)/100)::text)::uuid,md5(%s||'intent'||i::text)::uuid,decode(repeat('ab',32),'hex'),md5(%s||'input'||i::text)::uuid,md5(%s||'reply'||i::text)::uuid,'complete',0,'ollama',%s,1 FROM generate_series(%s::integer,%s::integer) i",
                (owner,) * 6 + (fixture.world.policy.dataset_key, first, last),
            )
    with fixture.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*),sum(octet_length(content)) FROM app.messages WHERE user_id=%s",
            (owner,),
        ).fetchone() == (6000, 6000000)
        assert conn.execute(
            "SELECT count(*) FROM app.analysis_requests WHERE user_id=%s", (owner,)
        ).fetchone() == (3000,)
        conn.execute(
            "INSERT INTO app.workspace_usage(user_id,content_bytes) VALUES(%s,6001000) ON CONFLICT(user_id) DO UPDATE SET content_bytes=EXCLUDED.content_bytes",
            (owner,),
        )
        conn.execute(
            "UPDATE app.workspace_totals SET content_bytes=content_bytes+6001000 WHERE singleton"
        )
    job, _ = fixture.queue(client)
    assert fixture.worker.once()
    with fixture.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT state,error_code FROM app.data_exports WHERE id=%s", (job["id"],)
        ).fetchone() == ("failed", "source_too_large")
        assert conn.execute(
            "SELECT count(*) FROM app.data_export_chunks WHERE job_id=%s", (job["id"],)
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT reserved_bytes,stored_bytes FROM app.privacy_control WHERE singleton"
        ).fetchone() == (0, 0)
    assert fixture.world.calls == []


def test_revoked_grant_snapshot_redacts_assistant_bytes_but_keeps_user_text(
    private_exports,
):
    fixture = private_exports
    client, owner = fixture.client(grant=True)
    fixture.world.submit(client, "MY-OWN-EXPORT-QUESTION")
    with fixture.world.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.dataset_grants SET revoked_at=clock_timestamp(),version=version+1 WHERE user_id=%s",
            (owner,),
        )
    _, raw, _ = fixture.ready(client, owner)
    payload = json.loads(raw)
    assert "MY-OWN-EXPORT-QUESTION" in raw.decode()
    answers = [item for item in payload["messages"] if item["role"] == "aqua"]
    assert answers and all(
        item["content"] == ""
        and item["response"] is None
        and item["result_unavailable"]
        for item in answers
    )
    assert b"Private fixture answer" not in raw and b"SELECT 7" not in raw


def test_deleting_owned_history_advances_privacy_epoch_and_fences_ready_bytes(
    private_exports,
):
    fixture = private_exports
    client, owner = fixture.client(grant=True)
    completed = fixture.world.submit(client)
    ready, _, _ = fixture.ready(client, owner)
    chat_id = completed["chat"]["id"]
    revision = client.get("/api/v1/chats/" + chat_id).json()["chat"]["revision"]
    deleted = client.delete("/api/v1/chats/" + chat_id, params={"revision": revision})
    assert deleted.status_code == 204, deleted.text
    status = client.get(EXPORTS + "/" + ready["id"]).json()["job"]
    assert status["state"] == "expired" and "sha256" not in status
    fixture.worker.once()
    assert fixture.bytes(owner, ready["id"]) == b""
    with fixture.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT privacy_epoch FROM app.users WHERE id=%s", (owner,)
        ).fetchone() == (2,)
        assert conn.execute(
            "SELECT reserved_bytes,stored_bytes FROM app.privacy_control WHERE singleton"
        ).fetchone() == (0, 0)


def test_expired_worker_lease_cannot_mint_a_second_physical_worker(private_exports):
    fixture = private_exports
    client, owner = fixture.client()
    job, _ = fixture.queue(client)
    competitor = ExportService(
        fixture.world.storage, fixture.world.policy, fixture.world.settings
    )
    try:
        with fixture.service.worker_pool.connection() as conn:
            assert conn.execute(
                "SELECT pg_try_advisory_lock(%s,0)", (WORKER_LOCK,)
            ).fetchone() == (True,)
            try:
                claimed = fixture.worker.claim(conn)
                with fixture.world.storage.transaction() as edit:
                    edit.execute(
                        "UPDATE app.data_exports SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",
                        (job["id"],),
                    )
                    edit.execute(
                        "UPDATE app.privacy_control SET worker_until=clock_timestamp()-interval '1 second' WHERE singleton"
                    )
                assert not Worker(competitor).once()
                with fixture.world.storage.transaction() as read:
                    assert read.execute(
                        "SELECT generation,attempts FROM app.data_exports WHERE user_id=%s AND id=%s",
                        (owner, job["id"]),
                    ).fetchone() == (claimed["generation"], 1)
            finally:
                conn.execute("SELECT pg_advisory_unlock(%s,0)", (WORKER_LOCK,))
        assert Worker(competitor).once()
        with fixture.world.storage.transaction() as conn:
            assert conn.execute(
                "SELECT state,generation,attempts FROM app.data_exports WHERE id=%s",
                (job["id"],),
            ).fetchone() == ("ready", 2, 2)
    finally:
        import anyio

        anyio.run(competitor.aclose)


def test_cleanup_is_bounded_and_accounted_once(private_exports):
    fixture = private_exports
    client, owner = fixture.client()
    ready, raw, _ = fixture.ready(client, owner)
    with fixture.world.storage.transaction() as conn:
        global_lock(conn)
        conn.execute("SELECT id FROM app.users WHERE id=%s FOR UPDATE", (owner,))
        row = records.expire(conn, records.get(conn, owner, ready["id"], lock=True))
        assert records.cleanup(conn, row)
        assert records.cleanup(conn, records.get(conn, owner, ready["id"], lock=True))
        assert conn.execute(
            "SELECT reserved_bytes,stored_bytes FROM app.privacy_control WHERE singleton"
        ).fetchone() == (0, 0)
    assert raw and fixture.bytes(owner, ready["id"]) == b""


def test_auth_cleanup_retains_export_session_until_private_cleanup(private_exports):
    fixture = private_exports
    client, owner = fixture.client()
    job, _ = fixture.queue(client)
    with fixture.world.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.sessions SET created_at=now()-interval '2 hours',idle_expires_at=now()-interval '2 seconds',absolute_expires_at=now()-interval '1 second' WHERE user_id=%s",
            (owner,),
        )
        cleanup(conn, fixture.world.policy)
        assert conn.execute(
            "SELECT count(*) FROM app.sessions WHERE user_id=%s", (owner,)
        ).fetchone() == (1,)
        assert records.get(conn, owner, job["id"])["state"] == "queued"


def test_review_cursor_is_bounded_and_bound_to_owner(private_exports):
    fixture = private_exports
    client, owner = fixture.client()
    job, _ = fixture.queue(client)
    token = Cursors(fixture.world.settings.session_secret, owner)
    with fixture.world.storage.transaction() as conn:
        row = records.get(conn, owner, job["id"])
    cursor = token.encode(0, row["created_at"], row["id"])
    assert token.decode(cursor)[0] == 0
    other = Cursors(fixture.world.settings.session_secret, str(uuid4()))
    with pytest.raises(WorkspaceError):
        other.decode(cursor)
    for suffix in ("?limit=100", "?cursor=" + "x" * 1025, "?cursor=x&cursor=y"):
        assert client.get(EXPORTS + suffix).status_code == 422
    listing = client.get(EXPORTS).json()
    assert set(listing) == {"schemaVersion", "user_id", "jobs", "next_cursor"}
    assert listing["user_id"] == owner and len(listing["jobs"]) <= 5


@pytest.mark.parametrize(
    "bad",
    [
        "csrf",
        "origin",
        "cross_site",
        "navigate",
        "no_cors",
        "destination",
        "prefetch",
        "range",
        "length",
        "query",
        "duplicate_csrf",
        "duplicate_origin",
    ],
)
def test_download_transport_rejects_before_authentication_sql(
    private_exports, monkeypatch, bad
):
    from auth.store import IdentityStore

    fixture = private_exports
    client, _ = fixture.client()
    path = EXPORTS + "/" + str(uuid4()) + "/download"
    headers = {}
    if bad == "csrf":
        headers["X-CSRF-Token"] = "wrong-session-pair"
    elif bad == "origin":
        headers["Origin"] = "https://other.fixture"
    elif bad == "cross_site":
        headers["Sec-Fetch-Site"] = "cross-site"
    elif bad in {"navigate", "no_cors"}:
        headers["Sec-Fetch-Mode"] = "navigate" if bad == "navigate" else "no-cors"
    elif bad == "destination":
        headers["Sec-Fetch-Dest"] = "document"
    elif bad == "prefetch":
        headers["Sec-Purpose"] = "prefetch"
    elif bad == "range":
        headers["Range"] = "bytes=0-"
    elif bad == "length":
        headers["Content-Length"] = "1"
    elif bad == "query":
        path += "?token=forged"
    elif bad == "duplicate_csrf":
        headers = [("x-csrf-token", client.headers["x-csrf-token"])] * 2
    else:
        headers = [("origin", fixture.world.settings.app_origin)] * 2

    def refuse(*args, **kwargs):
        raise AssertionError("bad export transport reached authentication SQL")

    monkeypatch.setattr(IdentityStore, "authenticate", refuse)
    response = client.get(path, headers=headers)
    assert response.status_code in {403, 422}, response.text
    with fixture.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.privacy_admission"
        ).fetchone() == (0,)


def test_export_capability_reuses_preference_field_and_closed_account_shape(
    private_exports,
):
    fixture = private_exports
    client, _ = fixture.client()
    preferences = client.get("/api/v1/me/preferences").json()
    assert preferences["capabilities"]["private_data_export"] is True
    methods = client.get("/api/v1/me/methods").json()
    assert methods["capabilities"]["recent_proof"] is True
    assert (
        len(methods["capabilities"]) == 13
        and "data_export" not in methods["capabilities"]
    )
    fixture.service.download_pool.closing = True
    assert (
        client.get("/api/v1/me/preferences").json()["capabilities"][
            "private_data_export"
        ]
        is False
    )
    fixture.service.download_pool.closing = False
    fixture.service.configured = False
    assert (
        client.get("/api/v1/me/preferences").json()["capabilities"][
            "private_data_export"
        ]
        is False
    )
