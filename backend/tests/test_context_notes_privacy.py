"""Notes-only exports and deletion exercise real private SQL, zero real providers."""

import asyncio
import hashlib
import json
from datetime import datetime
from urllib.parse import urlsplit

import anyio
import httpx
import main
import pytest

from context_notes.policy import ContextNotesPolicy
from privacy_export_fixture import EXPORTS
from test_context_notes_api import PATH, create, scope, select
from test_deletion_lifecycle import deletion as _deletion_fixture, request, settle

# Register the existing synthetic authority fixture, without duplicating its tests.
deletion = _deletion_fixture


def download(fixture, client, job_id):
    """Use the same bodyless ASGI framing as the real P11 transport tests."""

    origin = urlsplit(fixture.world.settings.app_origin)
    path = EXPORTS + "/" + job_id + "/download"
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": origin.scheme,
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "server": (origin.hostname, origin.port or 443),
        "client": ("127.0.0.1", 12345),
        "headers": [
            (b"host", origin.netloc.encode()),
            (
                b"cookie",
                "; ".join(
                    name + "=" + value for name, value in client.cookies.items()
                ).encode(),
            ),
            (b"origin", fixture.world.settings.app_origin.encode()),
            (b"x-csrf-token", client.headers["x-csrf-token"].encode()),
            (b"sec-fetch-site", b"same-origin"),
            (b"sec-fetch-mode", b"cors"),
            (b"sec-fetch-dest", b"empty"),
        ],
    }

    async def exercise():
        incoming = asyncio.Queue()
        incoming.put_nowait({"type": "http.request", "body": b"", "more_body": False})
        output = []

        async def send(message):
            output.append(message)

        try:
            # httpx.ASGITransport splits even an empty request into an initial
            # more_body=True event. The production attachment boundary rejects
            # that framing. Exercise main.app with a real bodyless final event,
            # exactly as the existing download transport tests do.
            await main.app(scope, incoming.get, send)
            assert output[0]["type"] == "http.response.start"
            assert output[-1]["type"] == "http.response.body"
            assert not output[-1].get("more_body", False)
            return httpx.Response(
                output[0]["status"],
                headers=output[0]["headers"],
                content=b"".join(
                    message.get("body", b"")
                    for message in output
                    if message["type"] == "http.response.body"
                ),
            )
        finally:
            # Pool and request share one loop; later fixture close is safe.
            await fixture.service.download_pool.aclose()

    return anyio.run(exercise)


@pytest.fixture
def note_exports(private_exports, monkeypatch):
    monkeypatch.setattr(
        main.app.state, "context_notes_policy", ContextNotesPolicy(True)
    )
    return private_exports


def test_new_format2_preserves_old_sections_and_scopes_only_current_note_content(
    note_exports,
):
    fixture = note_exports
    client, owner = fixture.client(grant=True)
    item = create(
        client, label="Current user definition", body="NOTE_ONLY_PRIVATE_CONTEXT"
    )
    prompt = client.post(
        "/api/v1/me/saved-prompts",
        json={
            "client_request_id": "12345678-1234-4234-8234-123456789012",
            "label": "Retained prompt",
            "prompt": "Original prompt\nwith exact text",
            "pinned": False,
        },
    )
    assert prompt.status_code == 201, prompt.text
    ready, raw, _ = fixture.ready(client, owner)
    value = json.loads(raw)
    assert value["schemaVersion"] == 2 and value["scope"] == "personal_v1"
    assert set(value) == {
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
        "context_notes",
    }
    assert value["profile"]["display_name"] == "A"
    assert value["preferences"]["schemaVersion"] == 1
    assert value["saved_prompts"][0]["prompt"] == "Original prompt\nwith exact text"
    exported = value["context_notes"][0]
    assert len(value["context_notes"]) == 1
    for key in ("created_at", "updated_at"):
        assert datetime.fromisoformat(exported[key]) == datetime.fromisoformat(
            item[key]
        )
    assert {
        key: part
        for key, part in exported.items()
        if key not in {"created_at", "updated_at"}
    } == {
        "id": item["id"],
        "revision": 1,
        "availability": "available",
        "kind": item["kind"],
        "label": item["label"],
        "body": item["body"],
    }
    assert value["messages"] == [] and fixture.world.calls == []
    downloaded = download(fixture, client, ready["id"])
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content == raw
    with fixture.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT contains_results,dataset_key,grant_version FROM app.data_exports WHERE id=%s",
            (ready["id"],),
        ).fetchone() == (True, fixture.world.policy.dataset_key, 1)
    assert b"grant_version" not in raw and b"dataset_key" not in raw


@pytest.mark.parametrize("change", ["revoke", "regrant"])
def test_notes_only_capture_cannot_publish_after_grant_changes(note_exports, change):
    fixture = note_exports
    client, owner = fixture.client(grant=True)
    create(client, body="MUST_NOT_PUBLISH_NOTE")
    job, _ = fixture.queue(client)

    def changed():
        with fixture.world.storage.transaction() as conn:
            assert conn.execute(
                "SELECT contains_results FROM app.data_exports WHERE id=%s",
                (job["id"],),
            ).fetchone() == (True,)
            conn.execute(
                "UPDATE app.dataset_grants SET version=version+1,revoked_at="
                + ("clock_timestamp()" if change == "revoke" else "NULL")
                + " WHERE user_id=%s",
                (owner,),
            )

    fixture.service.after_capture = changed
    assert fixture.worker.once()
    status = client.get(EXPORTS + "/" + job["id"]).json()["job"]
    assert status["state"] == "failed" and status["error_code"] == "authority_changed"
    assert fixture.bytes(owner, job["id"]) == b""
    assert fixture.world.calls == []


def test_revoked_note_exports_only_generic_owned_metadata(note_exports):
    fixture = note_exports
    client, owner = fixture.client(grant=True)
    item = create(
        client, label="DO_NOT_EXPORT_OLD_LABEL", body="DO_NOT_EXPORT_OLD_BODY"
    )
    with fixture.world.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.dataset_grants SET revoked_at=clock_timestamp(),version=version+1 WHERE user_id=%s",
            (owner,),
        )
    ready, raw, _ = fixture.ready(client, owner)
    assert json.loads(raw)["context_notes"] == [
        {"id": item["id"], "revision": 1, "availability": "unavailable"}
    ]
    assert b"DO_NOT_EXPORT" not in raw
    with fixture.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT contains_results FROM app.data_exports WHERE id=%s", (ready["id"],)
        ).fetchone() == (False,)


@pytest.mark.parametrize("operation", ["patch", "forget"])
def test_correction_and_forget_invalidate_already_staged_exports(
    note_exports, operation
):
    fixture = note_exports
    client, owner = fixture.client(grant=True)
    current = scope(client)
    item = create(client, current)
    ready, _, _ = fixture.ready(client, owner)
    if operation == "patch":
        response = client.patch(
            PATH + "/" + item["id"],
            json={
                **select(current, item),
                "kind": "note",
                "label": "Corrected",
                "body": "A new user statement.",
            },
        )
    else:
        response = client.post(
            PATH + "/" + item["id"] + "/forget", json=select(current, item)
        )
    assert response.status_code == 200, response.text
    assert client.get(EXPORTS + "/" + ready["id"]).json()["job"]["state"] == "expired"
    assert download(fixture, client, ready["id"]).status_code == 404


def test_ready_notes_only_download_loses_access_on_regrant(note_exports):
    fixture = note_exports
    client, owner = fixture.client(grant=True)
    create(client)
    ready, _, _ = fixture.ready(client, owner)
    with fixture.world.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.dataset_grants SET version=version+1 WHERE user_id=%s", (owner,)
        )
    assert download(fixture, client, ready["id"]).status_code == 404


def test_existing_ready_format1_bytes_download_without_rewriting(note_exports):
    fixture = note_exports
    client, owner = fixture.client()
    ready, raw, _ = fixture.ready(client, owner)
    # Construct an already-ready legacy snapshot as a fixture. The HTTP download
    # must treat its original bytes as immutable, not reserialize under format2.
    legacy = json.loads(raw)
    legacy["schemaVersion"] = 1
    del legacy["context_notes"]
    previous = json.dumps(legacy, ensure_ascii=False, separators=(",", ":")).encode()
    digest = hashlib.sha256(previous).hexdigest()
    with fixture.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.data_export_chunks WHERE job_id=%s",
            (ready["id"],),
        ).fetchone() == (1,)
        conn.execute(
            "UPDATE app.data_export_chunks SET body=%s,digest=%s WHERE job_id=%s",
            (previous, hashlib.sha256(previous).digest(), ready["id"]),
        )
        conn.execute(
            "UPDATE app.data_exports SET output_bytes=%s,sha256=%s WHERE id=%s",
            (len(previous), digest, ready["id"]),
        )
        conn.execute(
            "UPDATE app.privacy_control SET stored_bytes=stored_bytes+%s WHERE singleton",
            (len(previous) - len(raw),),
        )
    response = download(fixture, client, ready["id"])
    assert response.status_code == 200, response.text
    assert (
        response.content == previous
        and json.loads(response.content)["schemaVersion"] == 1
    )
    assert fixture.bytes(owner, ready["id"]) == previous


def test_history_deletion_retains_explicit_notes_but_retires_held_authority(
    deletion, monkeypatch
):
    secure, _, service, worker = deletion
    monkeypatch.setattr(
        main.app.state, "context_notes_policy", ContextNotesPolicy(True)
    )
    client, owner = secure.client(linked=True)
    old_scope = scope(client)
    item = create(client, old_scope)
    intent = request(secure, client, owner)
    accepted = client.post("/api/v1/me/data-deletions", json=intent)
    assert accepted.status_code == 202, accepted.text
    assert client.get(PATH).status_code == 409
    client.headers["X-Aqua-History-Revision"] = accepted.json()["history_revision"]
    settle(worker)
    assert client.get(PATH).json()["items"][0]["id"] == item["id"]
    assert (
        client.post(
            PATH + "/" + item["id"] + "/prepare", json=select(old_scope, item)
        ).status_code
        == 409
    )
    assert (
        client.post(
            PATH + "/" + item["id"] + "/prepare", json=select(scope(client), item)
        ).status_code
        == 200
    )
    with service.storage.transaction() as conn:
        assert conn.execute(
            "SELECT content_bytes=(SELECT sum(content_bytes) FROM app.context_notes WHERE user_id=%s) "
            "FROM app.workspace_usage WHERE user_id=%s",
            (owner, owner),
        ).fetchone() == (True,)
    assert secure.world.calls == []


def test_account_deletion_purges_notes_from_all_grants_without_other_owner_data(
    deletion, monkeypatch
):
    secure, _, service, worker = deletion
    monkeypatch.setattr(
        main.app.state, "context_notes_policy", ContextNotesPolicy(True)
    )
    client, owner = secure.client(linked=True)
    create(client, body="OLD_GRANT_NOTE")
    with service.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.dataset_grants SET version=version+1 WHERE user_id=%s", (owner,)
        )
    create(client, body="CURRENT_GRANT_NOTE")
    foreign, foreign_owner = secure.client("B", linked=True)
    foreign_note = create(foreign, body="FOREIGN_NOTE_REMAINS")
    intent = request(secure, client, owner, "account_v1")
    accepted = client.post("/api/v1/me/data-deletions", json=intent)
    assert accepted.status_code == 202, accepted.text
    assert client.get(PATH).status_code == 401
    settle(worker)
    with service.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.context_notes WHERE user_id=%s", (owner,)
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM app.users WHERE id=%s", (owner,)
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT body FROM app.context_notes WHERE user_id=%s AND id=%s",
            (foreign_owner, foreign_note["id"]),
        ).fetchone() == ("FOREIGN_NOTE_REMAINS",)
