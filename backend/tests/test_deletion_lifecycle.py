"""Real private app SQL, with explicit synthetic independent checkpoint outcomes."""

from contextlib import nullcontext
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import main

from auth.sessions import new_token, token_digest
from privacy.deletion_service import Deletions
from privacy.deletion_worker import Worker
from retirement.client import (
    ConfirmedAcceptance,
    ConfirmedRetirement,
    LocalCommit,
    PendingAuthority,
)
from retirement.fingerprints import IdentityKey
from retirement.interlock import RetirementUnavailable
from retirement.pages import manifest
from test_deletion_recent_auth import issue

PATH = "/api/v1/me/data-deletions"


class SyntheticAuthority:
    """An explicit fake cannot provision keys, sign a checkpoint or open a DB."""

    def __init__(self):
        self.broker = SimpleNamespace(
            installation=str(uuid4()),
            key=IdentityKey(str(uuid4()), b"fixture-retirement-key".ljust(32, b"0")),
        )
        self.originals, self.pages, self.sealed = {}, {}, set()
        self.published, self.available = True, True
        self.on_commit = None

    def intent_transaction(self, storage, owner, intent, scope, apply):
        with storage.transaction() as conn:
            result = apply(conn, self.originals.get(intent))
        if self.on_commit:
            self.on_commit()
        return LocalCommit(result)

    def prepare(self, record, fingerprints):
        if not self.available:
            raise RetirementUnavailable()
        original = self.originals.setdefault(record.intent, record)
        assert original == record
        self.pages.setdefault(record.intent, [])
        return PendingAuthority(
            record.intent,
            len(self.pages[record.intent]),
            "sealed" if record.intent in self.sealed else "staging",
        )

    def confirm_acceptance(self, owner, intent, scope):
        if not self.available or not self.published or intent not in self.originals:
            raise RetirementUnavailable()
        original = self.originals[intent]
        assert (owner, scope) == (original.owner, original.scope)
        record = replace(
            original,
            sequence=list(self.originals).index(intent) + 1,
            event_digest=token_digest(intent),
            checkpointed_at=original.created_at + timedelta(microseconds=1),
        )
        return ConfirmedAcceptance(record, record.sequence, record.event_digest)

    def append_page(self, intent, ordinal, previous, entries):
        assert ordinal == len(self.pages[intent])
        self.pages[intent].append(entries)

    def seal(self, intent):
        original = self.originals[intent]
        checked = manifest(value for page in self.pages[intent] for value in page)
        assert (checked.count, checked.root) == (
            original.fingerprint_count,
            original.fingerprint_root,
        )
        self.sealed.add(intent)

    def confirm(self, owner, intent, scope):
        acceptance = self.confirm_acceptance(owner, intent, scope)
        if intent not in self.sealed:
            return PendingAuthority(intent, len(self.pages[intent]), "staging", True)
        return ConfirmedRetirement(
            acceptance.record,
            acceptance.checkpoint_sequence,
            acceptance.checkpoint_digest,
        )


@pytest.fixture
def deletion(identity_security, monkeypatch):
    secure = identity_security
    # IdentityWorld adds its synthetic Google client after World constructed the
    # injected synchronous engine. Keep that explicit fixture generation current.
    secure.world.analysis.settings = secure.world.settings
    original_client = secure.client

    def client(*args, **kwargs):
        client, owner = original_client(*args, **kwargs)
        with secure.world.storage.transaction() as conn:
            conn.execute(
                "INSERT INTO app.dataset_grants(user_id,dataset_key) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                (owner, secure.world.policy.dataset_key),
            )
        return client, owner

    monkeypatch.setattr(secure, "client", client)
    authority = SyntheticAuthority()
    runtime = SimpleNamespace(
        installed=True,
        ready=True,
        client=authority,
        capable=lambda: True,
        purge_guard=lambda closed: nullcontext(True),
    )
    service = Deletions(
        secure.world.storage, secure.world.policy, secure.world.settings, runtime
    )
    monkeypatch.setattr(main.app.state, "deletions", service, raising=False)
    try:
        yield secure, authority, service, Worker(service)
    finally:
        service.close()


def request(secure, client, owner, scope="chat_history_v1"):
    intent = str(uuid4())
    operation = "history_delete" if scope == "chat_history_v1" else "account_delete"
    proof, _ = issue(secure, client, owner, "password", operation, intent)
    return {
        "intent_id": intent,
        "scope": scope,
        "proof_token": proof,
        "receipt_token": new_token(),
        "confirmation": (
            "DELETE HISTORY" if scope == "chat_history_v1" else "DELETE ACCOUNT"
        ),
    }


def status(client, body, **headers):
    return client.post(
        PATH + "/by-intent/" + body["intent_id"],
        json={},
        headers={"X-Aqua-Deletion-Receipt": body["receipt_token"], **headers},
    )


def settle(worker, limit=80):
    for _ in range(limit):
        worker.once()
        with worker.service.storage.transaction() as conn:
            if (
                conn.execute(
                    "SELECT 1 FROM app.deletion_jobs WHERE state<>'complete' LIMIT 1"
                ).fetchone()
                is None
            ):
                return
    pytest.fail("bounded synthetic cleanup did not settle")


def test_history_acceptance_fences_old_content_and_preserves_new_generation(deletion):
    secure, authority, service, worker = deletion
    client, owner = secure.client(linked=True)
    old = secure.world.submit(client)
    body = request(secure, client, owner)
    response = client.post(PATH, json=body)
    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["job"]["accepted"] and not payload["job"]["cleanup_complete"]
    assert client.get("/api/v1/chats").json()["items"] == []
    stale = client.post("/api/v1/chats", json=secure.world.body())
    assert stale.status_code == 409
    client.headers["X-Aqua-History-Revision"] = payload["history_revision"]
    fresh = secure.world.submit(client, "Fresh question")
    settle(worker)
    completed = status(client, body)
    assert completed.status_code == 200 and completed.json()["job"]["cleanup_complete"]
    with service.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.chats WHERE user_id=%s AND history_generation=1",
            (owner,),
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM app.chats WHERE user_id=%s AND history_generation=2",
            (owner,),
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT history_generation,privacy_epoch,status FROM app.users WHERE id=%s",
            (owner,),
        ).fetchone() == (2, 2, "active")
        charged = conn.execute(
            "SELECT content_bytes FROM app.workspace_usage WHERE user_id=%s", (owner,)
        ).fetchone()[0]
        actual = conn.execute(
            "SELECT (SELECT COALESCE(sum(octet_length(title)),0) FROM app.chats WHERE user_id=%s)+(SELECT COALESCE(sum(octet_length(content)),0) FROM app.messages WHERE user_id=%s)+(SELECT COALESCE(sum(octet_length(response::text)),0) FROM app.visual_results WHERE user_id=%s)",
            (owner, owner, owner),
        ).fetchone()[0]
        assert charged == actual
    assert old["chat"]["id"] != fresh["chat"]["id"]
    assert authority.sealed == {body["intent_id"]}


def test_unpublished_header_never_accepts_or_physically_purges_and_reconcile_recovers(
    deletion,
):
    secure, authority, service, worker = deletion
    client, owner = secure.client(linked=True)
    secure.world.submit(client)
    body = request(secure, client, owner)
    authority.published = False
    response = client.post(PATH, json=body)
    assert response.status_code == 503
    assert status(client, body).json()["job"]["accepted"] is False
    with pytest.raises(RetirementUnavailable):
        worker.once()
    with service.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.chats WHERE user_id=%s", (owner,)
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT consumed_at IS NOT NULL FROM app.account_action_proofs WHERE secret_digest=%s",
            (token_digest(body["proof_token"]),),
        ).fetchone() == (True,)
    authority.published = True
    assert status(client, body).json()["job"]["accepted"] is True
    assert client.post(PATH, json=body).status_code == 200
    with service.storage.transaction() as conn:
        assert conn.execute(
            "SELECT history_generation FROM app.users WHERE id=%s", (owner,)
        ).fetchone() == (2,)
    settle(worker)


@pytest.mark.parametrize("wrong", ("ticket", "cookie", "csrf", "origin", "scope"))
def test_receipt_is_bound_to_exact_original_purpose_cookie_and_browser_pair(
    deletion, wrong
):
    secure, authority, service, worker = deletion
    client, owner = secure.client(linked=True)
    body = request(secure, client, owner)
    assert client.post(PATH, json=body).status_code == 202
    if wrong == "scope":
        changed = {**body, "scope": "account_v1", "confirmation": "DELETE ACCOUNT"}
        assert client.post(PATH, json=changed).status_code in {403, 404}
    else:
        target = client
        headers = {}
        if wrong == "ticket":
            headers["X-Aqua-Deletion-Receipt"] = new_token()
        elif wrong == "cookie":
            target, _ = secure.client("B", linked=True)
        elif wrong == "csrf":
            headers["X-CSRF-Token"] = "wrong"
        else:
            headers["Origin"] = "https://foreign.invalid"
        assert status(target, body, **headers).status_code in {403, 404}
    assert status(client, body).json()["job"]["accepted"] is True


def test_account_closure_all_normal_routes_close_while_narrow_receipt_remains(deletion):
    secure, authority, service, worker = deletion
    client, owner = secure.client(linked=True)
    secure.world.submit(client)
    body = request(secure, client, owner, "account_v1")
    accepted = client.post(PATH, json=body)
    assert accepted.status_code == 202, accepted.text
    assert client.get("/api/v1/chats").status_code == 401
    assert client.get("/api/v1/me/preferences").status_code == 401
    assert client.post(
        "/api/v1/me/account/security/reauth-challenges",
        json={"operation": "account_delete", "target_intent_id": str(uuid4())},
    ).status_code in {401, 404}
    assert status(client, body).json()["job"]["accepted"] is True
    settle(worker)
    assert status(client, body).json()["job"]["cleanup_complete"] is True
    with service.storage.transaction() as conn:
        assert (
            conn.execute("SELECT 1 FROM app.users WHERE id=%s", (owner,)).fetchone()
            is None
        )
        assert conn.execute(
            "SELECT count(*) FROM app.retirement_intents WHERE user_id=%s", (owner,)
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT manifest_bytes FROM app.retirement_control"
        ).fetchone() == (0,)
    assert client.get("/api/v1/chats").status_code == 401


def test_missing_completed_job_never_means_completion_or_replays_floor(
    deletion, app_database
):
    secure, authority, service, worker = deletion
    client, owner = secure.client(linked=True)
    body = request(secure, client, owner)
    assert client.post(PATH, json=body).status_code == 202
    settle(worker)
    # Owner maintenance removes expired temporary metadata; permanent original
    # intent remains. The exact expiry trigger is tested independently below.
    app_database.execute("SET ROLE aqua_app_owner")
    app_database.execute(
        "ALTER TABLE app.deletion_jobs DISABLE TRIGGER deletion_job_immutable"
    )
    app_database.execute("DELETE FROM app.deletion_jobs")
    app_database.execute(
        "ALTER TABLE app.deletion_jobs ENABLE TRIGGER deletion_job_immutable"
    )
    app_database.execute("RESET ROLE")
    assert status(client, body).status_code == 404
    replayed = client.post(PATH, json=body)
    assert replayed.status_code in {403, 404}
    with service.storage.transaction() as conn:
        assert conn.execute(
            "SELECT history_generation FROM app.users WHERE id=%s", (owner,)
        ).fetchone() == (2,)


def test_session_revoked_before_acceptance_cannot_create_receipt_authority(deletion):
    secure, authority, service, worker = deletion
    client, owner = secure.client(linked=True)
    body = request(secure, client, owner)
    with service.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.sessions SET revoked_at=clock_timestamp() WHERE user_id=%s",
            (owner,),
        )
    response = client.post(PATH, json=body)
    assert response.status_code == 401
    assert status(client, body).status_code == 404
    with service.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.retirement_intents"
        ).fetchone() == (0,)
    assert not authority.originals


def test_download_lifetime_blocks_cleanup_even_after_old_private_rows_are_gone(
    deletion,
):
    from privacy.download import PHYSICAL

    secure, authority, service, worker = deletion
    client, owner = secure.client(linked=True)
    body = request(secure, client, owner)
    physical = PHYSICAL.acquire(owner)
    try:
        assert client.post(PATH, json=body).status_code == 202
        for _ in range(3):
            worker.once()
        assert status(client, body).json()["job"]["cleanup_complete"] is False
    finally:
        PHYSICAL.release(physical, owner)
    settle(worker)
    assert status(client, body).json()["job"]["cleanup_complete"] is True


def test_analysis_claim_requires_real_supervisor_exit_and_late_completion_is_fenced(
    deletion,
):
    from analysis.dispatch import Halt
    from analysis.lifecycle import terminate
    from analysis.records import get

    secure, authority, service, worker = deletion
    client, owner = secure.client(linked=True)
    queued = client.post("/api/v1/chats", json=secure.world.body())
    assert queued.status_code == 202
    original = secure.world.analysis.dispatch.claim(queued.json()["request"]["id"])
    assert original["physical_until"] is not None
    body = request(secure, client, owner)
    assert client.post(PATH, json=body).status_code == 202
    for _ in range(6):
        worker.once()
    assert status(client, body).json()["job"]["cleanup_complete"] is False
    with pytest.raises(Halt):
        secure.world.analysis.dispatch.check(original, "persisting")
    with service.storage.transaction() as conn:
        current = get(conn, owner, str(original["id"]), lock=True)
        assert current["physical_until"] is not None
        # This explicit fake engine had no child; model a supervisor's actual
        # exit acknowledgement rather than clearing it from a cleanup timeout.
        terminate(conn, current, "interrupted", reaped=True)
    settle(worker)
    assert status(client, body).json()["job"]["cleanup_complete"] is True
    assert secure.world.calls == []


def test_account_cleanup_waits_for_actual_mail_session_even_with_missing_mail_row(
    deletion,
):
    from auth.mailqueue import MailOutbox

    secure, authority, service, worker = deletion
    client, owner = secure.client(linked=True)
    body = request(secure, client, owner, "account_v1")
    assert client.post(PATH, json=body).status_code == 202
    box = MailOutbox(service.storage, secure.passwords.mail_policy)
    with box.physical() as acquired:
        assert acquired
        for _ in range(5):
            worker.once()
        # Query through the separately owned worker slot: the mail CLI's only
        # slot remains physically checked out, with no open transaction.
        assert box._connection.info.transaction_status == 0
        with service.pool.connection() as conn:
            assert (
                conn.execute("SELECT state FROM app.deletion_jobs").fetchone()[0]
                != "complete"
            )
            assert conn.execute("SELECT count(*) FROM app.account_mail").fetchone() == (
                0,
            )
    settle(worker)
    assert status(client, body).json()["job"]["cleanup_complete"] is True


def test_generation_race_before_local_acceptance_never_consumes_proof_or_creates_intent(
    deletion, monkeypatch
):
    secure, authority, service, worker = deletion
    client, owner = secure.client(linked=True)
    body = request(secure, client, owner)
    original = authority.intent_transaction

    def raced(storage, *args):
        with storage.transaction() as conn:
            conn.execute(
                "UPDATE app.users SET history_generation=history_generation+1 WHERE id=%s",
                (owner,),
            )
        return original(storage, *args)

    monkeypatch.setattr(authority, "intent_transaction", raced)
    response = client.post(PATH, json=body)
    assert response.status_code in {403, 409}
    with service.storage.transaction() as conn:
        assert conn.execute(
            "SELECT consumed_at IS NULL FROM app.account_action_proofs WHERE secret_digest=%s",
            (token_digest(body["proof_token"]),),
        ).fetchone() == (True,)
        assert conn.execute("SELECT count(*) FROM app.deletion_jobs").fetchone() == (0,)
    assert not authority.originals


def test_closed_account_new_uuid_cannot_reseed_legacy_google_or_mailbox_grants(
    deletion, monkeypatch
):
    from auth.accounts import ISSUER
    from auth.config import AuthDenied
    from auth.store import IdentityStore
    from retirement.pages import decode

    secure, authority, service, worker = deletion
    client, owner = secure.client(linked=True)
    body = request(secure, client, owner, "account_v1")
    assert client.post(PATH, json=body).status_code == 202
    settle(worker)
    calls = []

    def grant_transaction(storage, dataset, candidates, apply):
        calls.append(candidates)
        if not authority.available:
            raise RetirementUnavailable()
        fingerprints = {
            decode(value)
            for pages in authority.pages.values()
            for page in pages
            for value in page
        }
        retired = any(
            (key in {dataset, "0" * 64} and value in candidates)
            for key, value in fingerprints
        )
        with storage.transaction() as conn:
            return apply(conn, SimpleNamespace(retired=retired))

    monkeypatch.setattr(
        authority, "grant_transaction", grant_transaction, raising=False
    )
    monkeypatch.setattr(service.storage, "retirement", service.runtime, raising=False)
    policy = replace(
        secure.world.policy,
        allowed_google_subs=frozenset({"workspace-A", "new-subject"}),
        allowed_emails=frozenset({"a@gmail.com"}),
    )
    store = IdentityStore(service.storage, policy)
    identity = {
        "iss": ISSUER,
        "sub": "workspace-A",
        "email": "a@gmail.com",
        "email_verified": True,
    }
    raw = new_token()
    fresh = store.login(
        identity, token_digest(raw), b"c" * 32, "fixture-peer", secure.world.settings
    )
    assert fresh.user["id"] != owner and fresh.can_query is False
    assert calls and calls[0][0] == authority.broker.key.google(ISSUER, "workspace-A")
    with service.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.dataset_grants WHERE user_id=%s",
            (fresh.user["id"],),
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM app.chats WHERE user_id=%s", (fresh.user["id"],)
        ).fetchone() == (0,)
    authority.available = False
    with pytest.raises(AuthDenied):
        store.login(
            identity,
            token_digest(new_token()),
            b"d" * 32,
            "fixture-peer",
            secure.world.settings,
        )
