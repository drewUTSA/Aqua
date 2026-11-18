"""Fresh app authority, immutable producer, cooperative deadlines and budgets."""

from contextlib import contextmanager
import logging
from types import SimpleNamespace

import pytest

from auth.security import UserSession
from bank_demo.policy import BankDemoPolicy, load_policy
from bank_demo.service import BankDemo
from bank_demo.source import SyntheticReportSource
from mcp_demo.web import SOURCE_REVISION
from workspace.access_logging import PrivateWorkspaceAccess
from workspace.errors import WorkspaceError

SESSION = UserSession({"id": "33333333-3333-4333-8333-333333333333"}, "fixture-csrf")


class FakeWorkspace:
    policy = object()

    def __init__(self):
        self.reservations = 0
        self.storage = SimpleNamespace(transaction=self.transaction)

    def reserve(self, session):
        self.reservations += 1

    @contextmanager
    def transaction(self):
        yield object()


def test_host_policy_defaults_off_and_cannot_use_truthy_values_or_new_sources():
    assert load_policy({}) == BankDemoPolicy(False, "none")
    assert load_policy(
        {"BANK_DEMO_ENABLED": "true", "BANK_DEMO_PERSONA": "teller"}
    ) == BankDemoPolicy(True, "teller")
    for values in (
        {"BANK_DEMO_ENABLED": "TRUE"},
        {"BANK_DEMO_ENABLED": "1"},
        {"BANK_DEMO_PERSONA": "bank-admin"},
    ):
        with pytest.raises(ValueError):
            load_policy(values)
    for enabled in (1, "false", None):
        with pytest.raises(ValueError):
            BankDemoPolicy(enabled)
    with pytest.raises(ValueError):
        SyntheticReportSource("https://caller-source.invalid")


def test_disabled_policy_performs_no_admission_or_source_read():
    workspace = FakeWorkspace()
    with pytest.raises(WorkspaceError) as error:
        BankDemo(workspace, BankDemoPolicy()).read(SESSION)
    assert error.value.status == 404 and workspace.reservations == 0


def test_owner_is_fresh_app_session_and_guard_runs_before_and_after_source(monkeypatch):
    workspace, guards = FakeWorkspace(), []
    monkeypatch.setattr(
        "bank_demo.service.guard", lambda *args, **kwargs: guards.append(kwargs)
    )
    result = BankDemo(workspace, BankDemoPolicy(True, "teller")).read(SESSION)
    assert result["owner_id"] == SESSION.user["id"]
    assert result["context"]["persona"] == "teller"
    assert workspace.reservations == 1 and guards == [{"data": False}, {"data": False}]


def test_revocation_after_source_read_is_not_published(monkeypatch):
    calls = []

    def guard(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            raise WorkspaceError("session_invalid", 401)

    monkeypatch.setattr("bank_demo.service.guard", guard)
    with pytest.raises(WorkspaceError) as error:
        BankDemo(FakeWorkspace(), BankDemoPolicy(True, "manager")).read(SESSION)
    assert error.value.status == 401 and len(calls) == 2


def test_deadline_denies_work_after_admission_and_late_source_result(monkeypatch):
    monkeypatch.setattr("bank_demo.service.guard", lambda *args, **kwargs: None)
    for moments in ([0, 0, 2], [0, 0, 0, 0, 0, 2]):
        ticks = iter(moments)
        with pytest.raises(WorkspaceError) as error:
            BankDemo(
                FakeWorkspace(),
                BankDemoPolicy(True, "manager"),
                clock=lambda: next(ticks),
            ).read(SESSION)
        assert error.value.status == 503


def test_complete_outer_response_has_byte_budget(monkeypatch):
    monkeypatch.setattr("bank_demo.service.guard", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        SyntheticReportSource,
        "context",
        lambda *args: {"context": {"text": "é" * 17000}},
    )
    with pytest.raises(WorkspaceError) as error:
        BankDemo(FakeWorkspace(), BankDemoPolicy(True, "manager")).read(SESSION)
    assert error.value.status == 503


@pytest.mark.parametrize(
    "persona,report_id,revision,status",
    [
        ("none", "deposit_portfolio_summary", SOURCE_REVISION, 403),
        ("teller", "reconciliation_summary", SOURCE_REVISION, 403),
        ("manager", "run_arbitrary_sql", SOURCE_REVISION, 422),
        ("manager", "deposit_portfolio_summary", "a" * 64, 409),
    ],
)
def test_source_scope_and_revision_are_fixed_not_caller_authority(
    persona, report_id, revision, status
):
    with pytest.raises(WorkspaceError) as error:
        SyntheticReportSource(persona).report(report_id, revision, lambda: None)
    assert error.value.status == status


def test_private_path_and_query_canaries_do_not_reach_access_logs():
    for path in (
        "/api/v1/bank-demo/context?owner=PRIVATE-CANARY",
        "/api/v1/bank-demo/reports?persona=PRIVATE-CANARY",
    ):
        record = logging.LogRecord(
            "uvicorn.access",
            logging.INFO,
            "fixture",
            1,
            "%s %s %s %s %s",
            ("peer", "POST", path, "1.1", 200),
            None,
        )
        assert not PrivateWorkspaceAccess().filter(record)
