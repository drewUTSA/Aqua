"""Actual authenticated employee calculations with role-, period- and revision-bound sources."""

import pytest
import main
from bank_demo.policy import BankDemoPolicy
from mcp_demo.web import SOURCE_REVISION

BASE = "/api/v1/bank-demo"


@pytest.fixture
def employee(world, monkeypatch):
    monkeypatch.setattr(
        main.app.state, "bank_demo_policy", BankDemoPolicy(True, "analyst")
    )
    client, owner = world.client(grant=False)
    return client, owner


def body(op, params, **kwargs):
    return dict(
        schemaVersion=1,
        confirmed=True,
        currency="USD",
        operation=op,
        parameters=params,
        expected_source_revision=SOURCE_REVISION,
        **kwargs,
    )


@pytest.mark.parametrize(
    "operation,inputs,expected",
    [
        (
            "simple_interest",
            {"principal_usd": "912", "annual_rate_percent": "5", "term_months": "5"},
            {"interest_usd": "19.00"},
        ),
        (
            "simple_interest_actual_days",
            {
                "principal_usd": "16425",
                "annual_rate_percent": "4",
                "elapsed_days": "19",
                "day_count_basis": "Actual/365 Fixed",
            },
            {"interest_usd": "34.20"},
        ),
        (
            "amortizing_loan_payment",
            {"principal_usd": "801", "annual_rate_percent": "0", "term_months": "6"},
            {"scheduled_monthly_payment_usd": "133.50"},
        ),
        (
            "percent_change",
            {"previous_usd": "120", "current_usd": "93", "period": "month"},
            {"percent_change": "-22.500000"},
        ),
        (
            "liquidity_coverage",
            {
                "available_liquidity_usd": "1080",
                "projected_outflows_usd": "1200",
                "period": "quarter",
            },
            {"coverage_ratio": "0.900000", "surplus_or_shortfall_usd": "-120.00"},
        ),
        (
            "reconciliation",
            {
                "opening_balance_usd": "571",
                "credits_usd": "38",
                "debits_usd": "44",
                "reported_closing_balance_usd": "568",
                "period": "statement",
            },
            {"reported_less_expected_usd": "3.00"},
        ),
    ],
)
def test_employee_confirms_all_six_illustrations(employee, operation, inputs, expected):
    client, owner = employee
    r = client.post(BASE + "/calculations", json=body(operation, inputs))
    assert r.status_code == 200 and r.json()["owner_id"] == owner
    c = r.json()["calculation"]
    assert c["operation"] == operation and c["inputs"] == {**inputs, "currency": "USD"}
    assert expected.items() <= c["result"].items() and c["source"] == {
        "kind": "employee_supplied"
    }
    assert c["synthetic"] and not any(
        c[k] for k in ("executionEnabled", "bankQuote", "approvalRecorded")
    )


def test_report_principal_is_reread_with_its_original_field_and_period(employee):
    client, _ = employee
    ref = dict(
        report_id="commercial_exposure_summary",
        row=0,
        period_start="2026-11-01",
        period_end="2026-11-16",
        field="requested_usd",
    )
    inputs = {"annual_rate_percent": "2.5", "term_months": "12"}
    request = body("simple_interest", inputs, report=ref)
    reply = client.post(BASE + "/calculations", json=request).json()["calculation"]
    assert (
        reply["inputs"]["principal_usd"] == "120000.00"
        and reply["result"]["interest_usd"] == "3000.00"
    )
    assert (
        reply["source"]["rowLabels"]["Stage"] == "approved_not_funded"
        and reply["source"]["field"] == "requested_usd"
    )
    assert reply["source"]["sourceRevision"] == SOURCE_REVISION
    for key, value, status in (
        ("period_end", "2026-11-30", 409),
        ("row", 99, 422),
        ("field", "original_disbursed_usd", 422),
    ):
        res = client.post(
            BASE + "/calculations", json={**request, "report": {**ref, key: value}}
        )
        assert res.status_code == status and "120000" not in res.text
    res = client.post(
        BASE + "/calculations",
        json={**request, "parameters": {**inputs, "principal_usd": "1"}},
    )
    assert res.status_code == 422 and "120000" not in res.text


def test_statement_inputs_all_come_from_same_authorized_snapshot(employee):
    client, _ = employee
    req = body(
        "reconciliation",
        {"period": "statement"},
        report={
            "report_id": "reconciliation_summary",
            "row": 0,
            "period_start": "2026-11-01",
            "period_end": "2026-11-16",
            "field": "reconciliation_balances",
        },
    )
    reply = client.post(BASE + "/calculations", json=req).json()["calculation"]
    row = reply["source"]["rowLabels"]["Branch"]
    assert row in ("north", "central", "south")
    assert reply["result"]["reported_less_expected_usd"] == (
        "250.00" if row == "central" else "0.00"
    )
    assert (
        client.post(
            BASE + "/calculations", json={**req, "parameters": {"period": "quarter"}}
        ).status_code
        == 422
    )


def test_unconfirmed_wrong_scope_or_wrong_source_returns_no_numbers(
    employee, monkeypatch
):
    client, _ = employee
    req = body(
        "simple_interest",
        {"principal_usd": "7", "annual_rate_percent": "2", "term_months": "1"},
    )
    for values in (
        {"confirmed": False},
        {"confirmed": 1},
        {"persona": "manager"},
        {"schemaVersion": True},
    ):
        assert (
            client.post(BASE + "/calculations", json={**req, **values}).status_code
            == 422
        )
    assert (
        client.post(
            BASE + "/calculations", json={**req, "expected_source_revision": "a" * 64}
        ).status_code
        == 409
    )
    rejected = client.post(
        BASE + "/calculations",
        json=body(
            "percent_change", {"previous_usd": "0", "current_usd": "4", "period": "day"}
        ),
    )
    assert rejected.status_code == 200 and rejected.json()["unavailable"] == {
        "operation": "percent_change",
        "reason": "finance_positive_amount",
    }
    monkeypatch.setattr(
        main.app.state, "bank_demo_policy", BankDemoPolicy(True, "teller")
    )
    ref = {
        "report_id": "commercial_exposure_summary",
        "row": 0,
        "field": "requested_usd",
        "period_start": "2026-11-01",
        "period_end": "2026-11-16",
    }
    safe = client.post(BASE + "/calculations", json={**req, "report": ref})
    assert safe.status_code == 403 and "120000" not in safe.text
    monkeypatch.setattr(
        main.app.state, "bank_demo_policy", BankDemoPolicy(True, "none")
    )
    assert client.post(BASE + "/calculations", json=req).status_code == 403
    monkeypatch.setattr(
        main.app.state, "bank_demo_policy", BankDemoPolicy(False, "manager")
    )
    assert client.post(BASE + "/calculations", json=req).status_code == 404
