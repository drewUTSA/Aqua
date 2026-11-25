"""Confirmed fictional cash illustrations through the actual durable chat API."""

import pytest

from bank_demo.cash_chat import (
    ADJUSTED_HINT,
    AMOUNT_HINT,
    CURRENCY_HINT,
    WINDOW_HINT,
    _terms,
)
from bank_demo.policy import BankDemoPolicy

QUESTION = "For this quarter, will available cash of USD 3,027.00 cover expected outflows of USD 3,092.28?"


@pytest.mark.parametrize(
    ("question", "cash", "outflows", "window"),
    [
        (QUESTION, "3027.00", "3092.28", "this quarter"),
        (
            "Both amounts are USD. Will 482.19 in cash cover 299.20 in outgoing payments tomorrow?",
            "482.19",
            "299.20",
            "tomorrow",
        ),
        (
            "This month, projected outflows: 918.25 USD. Can available cash of 918.25 USD cover that?",
            "918.25",
            "918.25",
            "this month",
        ),
    ],
)
def test_exact_source_terms(question, cash, outflows, window):
    terms = _terms(question)
    assert {key: terms[key] for key in ("cash", "outflows", "window")} == {
        "cash": cash,
        "outflows": outflows,
        "window": window,
    }


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        (
            QUESTION.replace("expected outflows", "next month's expected outflows"),
            WINDOW_HINT,
        ),
        (QUESTION.replace("this quarter", "this week"), WINDOW_HINT),
        (QUESTION.replace("USD 3,092.28", "EUR 3,092.28"), CURRENCY_HINT),
        (QUESTION.replace("3,092.28", "3,092.28 nOk"), CURRENCY_HINT),
        (QUESTION.replace("USD 3,027.00", "USD -3,027.00"), AMOUNT_HINT),
        (QUESTION.replace("3,027.00", "3,027.00 million"), AMOUNT_HINT),
        (
            QUESTION.replace("USD 3,092.28", "an unknown amount"),
            "What are the projected outflows",
        ),
        (
            QUESTION.replace("USD 3,027.00", "an unknown amount"),
            "How much cash is available",
        ),
        (QUESTION + " Use the deposit report.", None),
        (QUESTION + " Execute a wire.", None),
        ("Which branch had the highest cash outflows last quarter?", None),
    ],
)
def test_clarifications_and_noncalculator_requests(question, expected):
    actual = _terms(question)
    assert actual is None if expected is None else actual.startswith(expected)


def test_owned_saved_confirmation_and_current_grant(world, monkeypatch):
    from mcp_demo import finance

    alice, owner = world.client("A")
    bob, peer = world.client("B")
    unscoped, _ = world.client("C")
    policy = BankDemoPolicy(True, "none", ((owner, "analyst"), (peer, "teller")))
    monkeypatch.setattr(world.analysis, "bank_policy", policy)
    calls = []
    original = finance.calculate_finance

    def observed(operation, parameters):
        calls.append((operation, parameters.copy()))
        return original(operation, parameters)

    monkeypatch.setattr(finance, "calculate_finance", observed)

    first = world.submit(alice, QUESTION)
    offer = first["response"]["bank_cash_review"]
    assert not calls and not world.calls
    path = f"/api/v1/chats/{first['chat']['id']}/messages"
    assert bob.get(path).status_code == 404
    assert alice.get(path).json()["items"][-1]["response"]["bank_cash_review"] == offer
    assert (
        "bank_calculation" not in world.submit(bob, offer["confirmation"])["response"]
    )
    denied = world.submit(unscoped, QUESTION)["response"]
    assert (
        "bank_cash_review" not in denied and "does not have access" in denied["message"]
    )
    assert (
        world.submit(unscoped, "Count our dataset rows")["response"]["sql"]
        == "SELECT 7"
    )
    assert not calls
    body = world.body(offer["confirmation"])
    sent = alice.post(path, json=body)
    assert sent.status_code == 202 and world.analysis.tick()
    saved = alice.get(
        "/api/v1/analysis-requests/" + sent.json()["request"]["id"]
    ).json()
    assert (
        saved["response"]["bank_calculation"]["result"]["surplus_or_shortfall_usd"]
        == "-65.28"
    )
    assert saved["response"]["bank_calculation"]["source"] == {
        "kind": "employee_supplied"
    }
    assert "falls short" in saved["response"]["message"]
    assert alice.post(path, json=body).json()["response"] == saved["response"]
    second = alice.post(path, json=world.body(offer["confirmation"]))
    assert second.status_code == 202 and world.analysis.tick()
    assert "bank_calculation" not in alice.get(path).json()["items"][-1]["response"]
    assert len(calls) == 1 and len(world.calls) == 1


@pytest.mark.parametrize(
    "clause",
    [
        "plus the unposted processing fee",
        "after reserving half the cash",
        "once our buffer is ring-fenced",
        "provided a third of the cash stays in escrow",
        "only if our undrawn line comes through",
        "assuming the vendor waives the surcharge",
        "adjusted for any conditional pledges",
    ],
)
def test_extra_qualifications_do_not_get_discarded(clause):
    question = f"Today our available cash is USD 809 and projected outflows are USD 698. Do we have enough {clause}?"
    assert _terms(question) == ADJUSTED_HINT


def test_named_period_references_and_earlier_or_later_windows():
    single = "For September our available cash is USD 300.51 and projected outflows for the same month are USD 373.41. Are we short?"
    assert _terms(single) == {
        "cash": "300.51",
        "outflows": "373.41",
        "period": "month",
        "window": "september",
    }
    assert _terms(single.replace("the same month", "August")) == WINDOW_HINT
