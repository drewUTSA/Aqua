"""Forged fields/cursors fail before storage, model or private delivery."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import main
from workspace.contracts import ChatPatch, FirstSubmission, ProjectCreate, PromptCreate
from workspace.cursors import Cursors
from workspace.errors import WorkspaceError


@pytest.mark.parametrize(
    "extra",
    [
        {"owner_id": str(uuid4())},
        {"user_id": str(uuid4())},
        {"response": {"sql": "DROP TABLE app.users"}},
        {"sql": "SELECT 1"},
        {"request_id": str(uuid4())},
        {"question": "x" * 2001},
        {"question": "   "},
        {"model": "arbitrary-tool"},
        {"question": "Null\x00text"},
        {"question": "\ud800"},
    ],
)
def test_submission_rejects_forged_or_unbounded_fields(extra):
    with pytest.raises(ValidationError):
        FirstSubmission.model_validate(
            {"client_request_id": str(uuid4()), "question": "Question", **extra}
        )


@pytest.mark.parametrize(
    "model,body",
    [
        (ChatPatch, {"revision": 1}),
        (ChatPatch, {"revision": 1, "title": None}),
        (ChatPatch, {"revision": 1, "archived": None}),
        (ProjectCreate, {"client_request_id": str(uuid4()), "name": "x" * 121}),
        (
            PromptCreate,
            {"client_request_id": str(uuid4()), "label": "Name", "prompt": ""},
        ),
    ],
)
def test_mutation_models_reject_invalid_contracts(model, body):
    with pytest.raises(ValidationError):
        model.model_validate(body)


def test_cursor_binds_owner_filters_and_stable_ties():
    a = Cursors("secret" * 12, "owner-a", {"kind": "chats", "search": "Loan"})
    value = a.encode(["2026-10-26T12:00:00+00:00", str(uuid4())])
    assert a.decode(value)[0] == "2026-10-26T12:00:00+00:00"
    for cursor in [
        Cursors("secret" * 12, "owner-b", {"kind": "chats", "search": "Loan"}),
        Cursors("secret" * 12, "owner-a", {"kind": "chats", "search": "Other"}),
    ]:
        with pytest.raises(WorkspaceError):
            cursor.decode(value)
    for bad in [value + "x", "x" * 1025, "not.a.cursor", "é"]:
        with pytest.raises(WorkspaceError):
            a.decode(bad)


@pytest.mark.parametrize(
    "body,content_type,status",
    [(b"{}", "text/plain", 415), (b"x" * 16385, "application/json", 413)],
)
def test_body_boundary_runs_before_auth_storage_and_json_parsing(
    body, content_type, status
):
    response = TestClient(main.app).post(
        "/api/v1/chats", content=body, headers={"Content-Type": content_type}
    )
    assert response.status_code == status
    assert response.json()["error"]["code"] == "invalid_request"
    assert response.headers["Cache-Control"] == "no-store"
