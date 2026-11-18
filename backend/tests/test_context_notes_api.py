"""Real isolated app roles/session/grants; no analytical or provider calls."""

from dataclasses import replace
from uuid import uuid4

import main
import pytest

from context_notes.policy import ContextNotesPolicy
from context_notes.service import ContextNotes
from workspace.service import Workspace
from workspace.errors import WorkspaceError

PATH = "/api/v1/me/context-notes"


@pytest.fixture
def notes(world, monkeypatch):
    monkeypatch.setattr(
        main.app.state, "context_notes_policy", ContextNotesPolicy(True)
    )
    return world


def scope(client):
    result = client.get(PATH)
    assert result.status_code == 200, result.text
    return result.json()["scope"]["id"]


def creation(current, **changes):
    return {
        "schemaVersion": 1,
        "client_request_id": str(uuid4()),
        "expected_scope_id": current,
        "kind": "metric_definition",
        "label": "User-defined measure",
        "body": "Verify this definition before using it.",
        **changes,
    }


def create(client, current=None, **changes):
    response = client.post(PATH, json=creation(current or scope(client), **changes))
    assert response.status_code == 201, response.text
    return response.json()["note"]


def select(current, note):
    return {
        "schemaVersion": 1,
        "expected_scope_id": current,
        "revision": note["revision"],
    }


def test_notes_are_an_explicit_library_and_prepare_does_not_submit(notes):
    client, owner = notes.client()
    current = scope(client)
    submitted = creation(
        current, body="A user claim\n\twith literal <tags> and no execution."
    )
    result = client.post(PATH, json=submitted)
    assert result.status_code == 201, result.text
    note = result.json()["note"]
    assert result.json()["owner_id"] == owner
    assert (
        result.json()["unverified"] is True
        and result.json()["execution_enabled"] is False
    )
    listed = client.get(PATH)
    assert all("body" not in item for item in listed.json()["items"])
    assert submitted["body"] not in listed.text
    assert listed.json()["items"][0]["label"] == submitted["label"]
    detail = client.get(PATH + "/" + note["id"])
    assert detail.json()["note"] == note and len(detail.content) <= 32768
    prepared = client.post(
        PATH + "/" + note["id"] + "/prepare", json=select(current, note)
    )
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["draft"] == submitted["body"]
    assert prepared.json()["requires_review"] is True
    assert "dataset_key" not in prepared.text and "grant_version" not in prepared.text
    assert prepared.headers["cache-control"] == "no-store"
    assert "cookie" in prepared.headers["vary"].lower()
    assert prepared.headers.get("x-aqua-history-revision")
    assert client.get("/api/v1/chats").json()["items"] == []
    assert notes.calls == []


def test_default_off_foreign_ids_and_request_authority_claims_do_not_leak(
    notes, monkeypatch
):
    first, _ = notes.client("A")
    second, _ = notes.client("B")
    item = create(first)
    other_scope = scope(second)
    for target in (item["id"], str(uuid4())):
        assert second.get(PATH + "/" + target).status_code == 404
        for action in ("prepare", "forget"):
            response = second.post(
                PATH + "/" + target + "/" + action, json=select(other_scope, item)
            )
            assert response.status_code == 404 and item["body"] not in response.text
    for claim in ("owner_id", "dataset_key", "grant_version", "role", "instructions"):
        response = first.post(PATH, json=creation(scope(first), **{claim: "forged"}))
        assert response.status_code == 422
    monkeypatch.setattr(main.app.state, "context_notes_policy", ContextNotesPolicy())
    assert first.get(PATH).status_code == 404


def test_create_replay_and_correction_are_cas_not_scope_transfer(notes):
    client, owner = notes.client()
    current = scope(client)
    body = creation(current)
    first = client.post(PATH, json=body)
    assert first.status_code == 201
    item = first.json()["note"]
    replay = client.post(PATH, json=body)
    assert replay.status_code == 200 and replay.json()["note"] == item
    assert client.post(PATH, json={**body, "body": "Different"}).status_code == 409
    changed = client.patch(
        PATH + "/" + item["id"],
        json={
            **select(current, item),
            "kind": "note",
            "label": "Correction",
            "body": "Corrected user statement.",
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["note"]["revision"] == 2
    assert (
        client.patch(
            PATH + "/" + item["id"],
            json={
                **select(current, item),
                "kind": "note",
                "label": "Stale",
                "body": "Must not win.",
            },
        ).status_code
        == 409
    )
    assert (
        client.post(
            PATH + "/" + item["id"] + "/prepare", json=select(current, item)
        ).status_code
        == 409
    )
    with notes.storage.transaction() as conn:
        assert conn.execute(
            "SELECT privacy_epoch FROM app.users WHERE id=%s", (owner,)
        ).fetchone() == (2,)
        assert conn.execute(
            "SELECT count(*) FROM app.context_notes WHERE user_id=%s", (owner,)
        ).fetchone() == (1,)


@pytest.mark.parametrize("change", ["revoke", "regrant", "dataset"])
def test_unavailable_scopes_hide_body_but_owner_can_forget(notes, monkeypatch, change):
    client, owner = notes.client()
    old_scope = scope(client)
    item = create(
        client, old_scope, label="SCOPE_PRIVATE_LABEL", body="SCOPE_PRIVATE_BODY"
    )
    if change == "dataset":
        monkeypatch.setattr(
            main.app.state,
            "settings",
            replace(notes.settings, database_url="other-synthetic-dataset"),
        )
    else:
        with notes.storage.transaction() as conn:
            conn.execute(
                "UPDATE app.dataset_grants SET version=version+1,revoked_at="
                + ("clock_timestamp()" if change == "revoke" else "NULL")
                + " WHERE user_id=%s",
                (owner,),
            )
    listing = client.get(PATH)
    assert listing.status_code == 200
    assert "SCOPE_PRIVATE" not in listing.text
    assert listing.json()["items"] == [
        {
            "id": item["id"],
            "revision": 1,
            "availability": "unavailable",
            "label": "Unavailable saved context",
            "kind": None,
            "created_at": None,
            "updated_at": None,
        }
    ]
    fresh = listing.json()["scope"]["id"]
    assert fresh != old_scope
    assert client.get(PATH + "/" + item["id"]).status_code in {403, 404}
    assert client.post(
        PATH + "/" + item["id"] + "/prepare", json=select(fresh, item)
    ).status_code in {403, 404}
    forgotten = client.post(
        PATH + "/" + item["id"] + "/forget", json=select(fresh, item)
    )
    assert forgotten.status_code == 200, forgotten.text
    with notes.storage.transaction() as conn:
        row = conn.execute(
            "SELECT label,body,content_bytes,fingerprint,deleted_at IS NOT NULL FROM app.context_notes WHERE id=%s",
            (item["id"],),
        ).fetchone()
        assert row == ("Deleted context", "", 0, bytes(32), True)
    assert "SCOPE_PRIVATE" not in forgotten.text


def test_history_change_retains_library_but_blocks_old_reads_and_mutations(notes):
    client, owner = notes.client()
    current = scope(client)
    item = create(client, current)
    old_header = client.get(PATH).headers["x-aqua-history-revision"]
    with notes.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.users SET history_generation=history_generation+1 WHERE id=%s",
            (owner,),
        )
    for method, target, data in (
        ("GET", PATH, None),
        ("GET", PATH + "/" + item["id"], None),
        ("POST", PATH, creation(current)),
        ("POST", PATH + "/" + item["id"] + "/prepare", select(current, item)),
    ):
        response = client.request(
            method, target, json=data, headers={"X-Aqua-History-Revision": old_header}
        )
        assert response.status_code == 409
    # Session bootstrap advertises the fresh generation; only a new deliberate
    # intent may use it. The existing saved library itself survives history clear.
    from retirement.revision import history_revision

    client.headers["X-Aqua-History-Revision"] = history_revision(
        notes.settings.session_secret, owner, 2
    )
    assert client.get(PATH).json()["items"][0]["id"] == item["id"]
    assert (
        client.post(
            PATH + "/" + item["id"] + "/prepare", json=select(current, item)
        ).status_code
        == 409
    )
    assert (
        client.post(
            PATH + "/" + item["id"] + "/prepare", json=select(scope(client), item)
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    "body",
    [
        b"\xff",
        b"\xef\xbb\xbf{}",
        b'{"schemaVersion":1,"schemaVersion":1}',
        b"\x00",
        '{"schemaVersion":1}'.encode("utf-16"),
        b"x" * 8193,
    ],
)
def test_raw_json_is_bounded_utf8_and_unambiguous(notes, body):
    client, _ = notes.client()
    response = client.post(
        PATH, content=body, headers={"content-type": "application/json"}
    )
    assert response.status_code in {413, 422}
    assert b"\\ufffd" not in response.content


def test_text_boundary_preserves_exact_composer_compatible_body(notes):
    client, _ = notes.client()
    current = scope(client)
    valid = "a" * 1998 + "\U0001f600"
    item = create(client, current, body=valid)
    assert (
        client.post(
            PATH + "/" + item["id"] + "/prepare", json=select(current, item)
        ).json()["draft"]
        == valid
    )
    for value in ("a" * 1999 + "\U0001f600", "é" * 1025, "a\rb", "a\u202eb"):
        assert client.post(PATH, json=creation(current, body=value)).status_code == 422
    assert client.get(PATH + "?owner_id=forged").status_code == 422
    assert client.request("GET", PATH, content=b"x").status_code == 413


def test_account_quota_and_forget_refund_without_reusing_tombstones(notes):
    client, owner = notes.client()
    current = scope(client)
    items = [
        create(client, current, label=f"Note {index}", body="x") for index in range(20)
    ]
    denied = client.post(PATH, json=creation(current))
    assert (
        denied.status_code == 429
        and denied.json()["error"]["code"] == "capacity_reached"
    )
    assert (
        client.post(
            PATH + "/" + items[0]["id"] + "/forget", json=select(current, items[0])
        ).status_code
        == 200
    )
    with notes.storage.transaction() as conn:
        size = conn.execute(
            "SELECT sum(content_bytes) FROM app.context_notes WHERE user_id=%s",
            (owner,),
        ).fetchone()[0]
        assert conn.execute(
            "SELECT content_bytes FROM app.workspace_usage WHERE user_id=%s", (owner,)
        ).fetchone() == (size,)
    create(client, current)
    assert len(client.get(PATH).json()["items"]) == 20
    assert client.get(PATH + "/" + items[0]["id"]).status_code == 404


def test_deadline_rolls_back_note_and_accounting_but_not_admission(notes):
    client, owner = notes.client()
    current = scope(client)
    ticks = iter([0, 0, 0, 3])
    service = ContextNotes(
        Workspace(notes.storage, notes.policy, notes.settings.session_secret),
        ContextNotesPolicy(True),
        clock=lambda: next(ticks),
    )
    from context_notes.contracts import NoteCreate

    with pytest.raises(WorkspaceError) as caught:
        service.perform(
            notes.sessions[owner],
            "create",
            body=NoteCreate.model_validate(creation(current)),
        )
    assert caught.value.status == 503
    with notes.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.context_notes WHERE user_id=%s", (owner,)
        ).fetchone() == (0,)
        assert (
            conn.execute(
                "SELECT content_bytes FROM app.workspace_usage WHERE user_id=%s",
                (owner,),
            ).fetchone()
            is None
        )
        assert (
            conn.execute(
                "SELECT hits FROM app.workspace_admission WHERE user_id=%s", (owner,)
            ).fetchone()[0]
            >= 2
        )


def test_scrubbed_tombstones_still_bound_owner_metadata(notes):
    client, owner = notes.client()
    current = scope(client)
    with notes.storage.transaction() as conn:
        conn.execute(
            "INSERT INTO app.context_notes(user_id,dataset_key,grant_version,kind,label,body,"
            "client_request_id,fingerprint,content_bytes,deleted_at) "
            "SELECT %s,%s,1,'note','Deleted context','',gen_random_uuid(),"
            "decode(repeat('00',32),'hex'),0,clock_timestamp() FROM generate_series(1,200)",
            (owner, notes.policy.dataset_key),
        )
    assert client.get(PATH).json()["items"] == []
    response = client.post(PATH, json=creation(current))
    assert (
        response.status_code == 429
        and response.json()["error"]["code"] == "capacity_reached"
    )


def test_global_note_row_cap_is_shared_across_owners(notes):
    client, _ = notes.client()
    current = scope(client)
    with notes.storage.transaction() as conn:
        conn.execute(
            "WITH owners AS (INSERT INTO app.users(display_name) "
            "SELECT 'Synthetic metadata owner' FROM generate_series(1,25) RETURNING id) "
            "INSERT INTO app.context_notes(user_id,dataset_key,grant_version,kind,label,body,"
            "client_request_id,fingerprint,content_bytes,deleted_at) "
            "SELECT owners.id,%s,1,'note','Deleted context','',gen_random_uuid(),"
            "decode(repeat('00',32),'hex'),0,clock_timestamp() "
            "FROM owners CROSS JOIN generate_series(1,200)",
            (notes.policy.dataset_key,),
        )
    response = client.post(PATH, json=creation(current))
    assert (
        response.status_code == 429
        and response.json()["error"]["code"] == "capacity_reached"
    )


@pytest.mark.parametrize("change", ["session", "account", "csrf", "origin"])
def test_fresh_authentication_and_csrf_precede_note_mutation(notes, change):
    client, owner = notes.client()
    current = scope(client)
    headers = {}
    if change == "csrf":
        headers["X-CSRF-Token"] = "not-the-paired-token"
    elif change == "origin":
        headers["Origin"] = "https://foreign.fixture"
    else:
        with notes.storage.transaction() as conn:
            if change == "session":
                conn.execute(
                    "UPDATE app.sessions SET revoked_at=clock_timestamp() WHERE user_id=%s",
                    (owner,),
                )
            else:
                conn.execute(
                    "UPDATE app.users SET status='disabled' WHERE id=%s", (owner,)
                )
    response = client.post(PATH, json=creation(current), headers=headers)
    assert response.status_code == (403 if change in {"csrf", "origin"} else 401)
    with notes.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.context_notes WHERE user_id=%s", (owner,)
        ).fetchone() == (0,)


def test_preferences_remain_separate_and_never_accept_note_instructions(notes):
    client, _ = notes.client()
    item = create(client)
    preferences = client.get("/api/v1/me/preferences").json()
    assert preferences["capabilities"]["personal_instructions"] is False
    values = preferences["values"]
    invalid = client.put(
        "/api/v1/me/preferences",
        json={
            "schemaVersion": 1,
            "expectedRevision": preferences["revision"],
            "values": {**values, "context_notes": ["not an allowed preference"]},
        },
    )
    assert invalid.status_code == 422
    saved = client.put(
        "/api/v1/me/preferences",
        json={
            "schemaVersion": 1,
            "expectedRevision": preferences["revision"],
            "values": values,
        },
    )
    assert saved.status_code == 200
    assert client.get(PATH + "/" + item["id"]).json()["note"] == item
