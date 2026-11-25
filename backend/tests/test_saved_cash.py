"""Confirmed fictional cash illustrations through the actual durable chat API."""

import pytest

from bank_demo.cash_chat import (
    ADJUSTED_HINT,
    AMOUNT_HINT,
    CURRENCY_HINT,
    EXACT_HINT,
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


def test_locally_handled_numbers_are_excluded_from_analytical_context(
    world, monkeypatch
):
    alice, owner = world.client()
    monkeypatch.setattr(
        world.analysis,
        "bank_policy",
        BankDemoPolicy(True, "none", ((owner, "analyst"),)),
    )
    review = world.submit(alice, QUESTION)
    path = f"/api/v1/chats/{review['chat']['id']}/messages"
    terms = review["response"]["bank_cash_review"]["confirmation"]
    confirmed = alice.post(path, json=world.body(terms))
    assert confirmed.status_code == 202 and world.analysis.tick()
    assert "bank_calculation" in alice.get(path).json()["items"][-1]["response"]
    payloads = []
    original_run = world.analysis.engine.run

    def observe_payload(payload, control):
        payloads.append(payload)
        return original_run(payload, control)

    monkeypatch.setattr(world.analysis.engine, "run", observe_payload)
    next_turn = alice.post(path, json=world.body("Count the dataset rows"))
    assert next_turn.status_code == 202 and world.analysis.tick()
    assert len(payloads) == 1 and payloads[0]["context"] == []


def test_role_removed_between_offer_and_confirmation(world, monkeypatch):
    employee, owner = world.client()
    monkeypatch.setattr(
        world.analysis,
        "bank_policy",
        BankDemoPolicy(True, "none", ((owner, "manager"),)),
    )
    first = world.submit(employee, QUESTION)
    ack = first["response"]["bank_cash_review"]["confirmation"]
    path = f"/api/v1/chats/{first['chat']['id']}/messages"
    monkeypatch.setattr(world.analysis, "bank_policy", BankDemoPolicy(True, "none", ()))
    assert employee.post(path, json=world.body(ack)).status_code == 202
    assert world.analysis.tick()
    denied = employee.get(path).json()["items"][-1]["response"]
    assert (
        denied["bank_cash_reply"]
        and "access" in denied["message"]
        and "bank_calculation" not in denied
    )
    assert not world.calls


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


@pytest.mark.parametrize(
    "outgoing",
    ["cash outflows", "cash payments", "cash payables", "cash disbursements"],
)
def test_an_outgoing_noun_cannot_provide_the_available_cash_operand(outgoing):
    text = f"Can USD 119 in {outgoing} cover USD 63 of expected payments today?"
    assert _terms(text).startswith("What cash is available")
    fully_labelled = (
        f"Can USD 119 in available cash cover USD 63 of projected {outgoing} today?"
    )
    assert _terms(fully_labelled) == {
        "cash": "119.00",
        "outflows": "63.00",
        "period": "day",
        "window": "today",
    }


def test_stated_worksheet_keeps_labels_without_swallowing_adjustments():
    text = "Our daily funding worksheet lists USD 811 of projected cash outflows and USD 715 in available cash today. Can we cover them?"
    assert _terms(text) == {
        "cash": "715.00",
        "outflows": "811.00",
        "period": "day",
        "window": "today",
    }
    assert _terms(text + " Account for the unposted dividend.") == ADJUSTED_HINT


@pytest.mark.parametrize(
    "qualifier", ["more than", "over", "at most", "roughly", "up to"]
)
def test_bounds_cannot_produce_an_exact_difference(qualifier):
    question = f"For today, compare {qualifier} USD 480 of available cash with USD 386 in projected outflows."
    assert _terms(question) == EXACT_HINT


def test_cash_receivable_does_not_supply_a_spendable_balance():
    question = "Can USD 609 cash in trust cover USD 804 of forecast payments today?"
    assert "unrestricted" in _terms(question)


@pytest.mark.parametrize(
    "metric",
    [
        "cash surplus",
        "outflow shortfall",
        "cash coverage gap",
        "cushion in available cash",
    ],
)
def test_a_result_measure_cannot_be_promoted_to_an_operand(metric):
    text = f"Can USD 688 in {metric} cover projected outflows of USD 590 today? Our total available cash is unclear."
    assert not isinstance(_terms(text), dict)


def test_a_separate_result_clause_cannot_hide_an_adjustment():
    text = (
        "For this quarter, available cash is USD 120 and planned outflows are USD 105."
    )
    assert isinstance(_terms(text + " How much money will remain?"), dict)
    assert not isinstance(
        _terms(text + " How much money will remain after the dividend?"), dict
    )
