"""Fresh job-specific authority before and after an isolated saved-result read."""

from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from auth.security import UserSession
from companion.policy import CompanionPolicy
from result_companion.service import ResultCompanion
from result_companion_fixtures import response
from workspace.errors import WorkspaceError

OWNER, REQUEST, CHAT, REPLY = (
    f"{value}0000000-0000-4000-8000-000000000001" for value in "1234"
)
SESSION = UserSession({"id": OWNER}, "fixture-csrf")


class Workspace:
    policy = object()

    def __init__(self):
        self.reservations = 0
        self.storage = SimpleNamespace(transaction=self.transaction)

    def reserve(self, session):
        self.reservations += 1

    @contextmanager
    def transaction(self):
        yield object()


@pytest.fixture
def setup(monkeypatch):
    job = {"id": REQUEST, "request_id": REQUEST, "state": "complete", "version": 3}
    saved = {
        "chat": {"id": CHAT},
        "request": {"id": REQUEST, "state": "complete", "reply_message_id": REPLY},
        "assistant_message": {
            "id": REPLY,
            "chat_id": CHAT,
            "request_id": REQUEST,
            "response": response(),
        },
        "input_message": {"content": "Original synthetic question"},
    }
    calls = []

    def get(conn, owner, request):
        assert owner == OWNER and request == REQUEST
        calls.append("owned_get")
        return job

    def authorize(conn, session, policy, observed):
        assert observed is job and session is SESSION
        calls.append("job_authorize")
        return session

    monkeypatch.setattr("result_companion.service.records.get", get)
    monkeypatch.setattr("result_companion.service.records.authorize", authorize)
    monkeypatch.setattr(
        "result_companion.service.records.snapshot",
        lambda *args: calls.append("snapshot") or saved,
    )
    return Workspace(), job, saved, calls


def test_disabled_flag_reads_nothing(setup):
    workspace, _, _, calls = setup
    with pytest.raises(WorkspaceError) as error:
        ResultCompanion(workspace, CompanionPolicy()).read(
            SESSION, request_id=REQUEST, column_index=0
        )
    assert error.value.status == 404 and workspace.reservations == 0 and calls == []


def test_same_owned_job_is_authorized_twice_and_no_draft_or_execution_is_applied(setup):
    workspace, _, saved, calls = setup
    before = deepcopy(saved)
    value = ResultCompanion(workspace, CompanionPolicy(True)).read(
        SESSION, request_id=REQUEST, column_index=0
    )
    assert workspace.reservations == 1 and calls == [
        "owned_get",
        "job_authorize",
        "snapshot",
        "job_authorize",
    ]
    assert (
        value["owner_id"] == OWNER
        and value["request_id"] == REQUEST
        and value["assistant_message_id"] == REPLY
        and value["job_version"] == 3
    )
    assert value["brief"]["execution_enabled"] is False and saved == before


def test_revocation_on_second_authorization_cannot_publish(setup, monkeypatch):
    workspace, _, _, calls = setup

    def authorize(*args):
        if "snapshot" in calls:
            raise WorkspaceError("access_denied", 403)
        return SESSION

    monkeypatch.setattr("result_companion.service.records.authorize", authorize)
    with pytest.raises(WorkspaceError) as error:
        ResultCompanion(workspace, CompanionPolicy(True)).read(
            SESSION, request_id=REQUEST, column_index=0
        )
    assert error.value.status == 403


@pytest.mark.parametrize(
    "state",
    ["queued", "running", "error", "cancelled", "interrupted", "expired", "legacy"],
)
def test_only_a_completed_linked_durable_job_can_be_explained(setup, state):
    workspace, job, _, calls = setup
    if state == "legacy":
        job["request_id"] = None
    else:
        job["state"] = state
    with pytest.raises(WorkspaceError) as error:
        ResultCompanion(workspace, CompanionPolicy(True)).read(
            SESSION, request_id=REQUEST, column_index=0
        )
    assert error.value.status == 404 and "snapshot" not in calls


def test_late_projection_does_not_start_another_authorization_or_publish(
    setup, monkeypatch
):
    workspace, _, _, calls = setup
    clock = SimpleNamespace(now=0)

    def late(*args):
        clock.now = 3
        return {}

    monkeypatch.setattr("result_companion.service.build", late)
    with pytest.raises(WorkspaceError) as error:
        ResultCompanion(workspace, CompanionPolicy(True), clock=lambda: clock.now).read(
            SESSION, request_id=REQUEST, column_index=0
        )
    assert error.value.status == 503 and calls.count("job_authorize") == 1


def test_out_of_range_field_is_not_an_arbitrary_source_lookup(setup):
    workspace, _, _, _ = setup
    with pytest.raises(WorkspaceError) as error:
        ResultCompanion(workspace, CompanionPolicy(True)).read(
            SESSION, request_id=REQUEST, column_index=1
        )
    assert error.value.status == 422
