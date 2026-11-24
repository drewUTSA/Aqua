"""Synthetic HTTP reads retain real Aqua session/CSRF/admission protections."""

import json
from types import SimpleNamespace

import pytest

import main
from bank_demo.policy import BankDemoPolicy
from mcp_demo.web import SOURCE_REVISION

BASE = "/api/v1/bank-demo"


def body(**changes):
    return {
        "schemaVersion": 1,
        "report_id": "deposit_portfolio_summary",
        "expected_source_revision": SOURCE_REVISION,
        **changes,
    }


@pytest.mark.parametrize(
    "source,start,end,reason",
    [
        ("fictional_snapshot", "2026-11-01", "2026-11-16", None),
        ("fictional_snapshot", "2026-11-01", "2026-11-30", "period_unavailable"),
        ("fictional_snapshot", "2026-11-11", "2026-11-16", "period_unavailable"),
        ("fictional_snapshot", None, None, "period_required"),
        (
            "institution_record",
            "2026-11-01",
            "2026-11-16",
            "institution_source_unavailable",
        ),
    ],
)
def test_requested_report_matches_source_and_full_range(
    enabled, source, start, end, reason
):
    client, owner = enabled.client(grant=False)
    request = {"source": source, "period_start": start, "period_end": end}
    reply = client.post(BASE + "/reports", json=body(requirements=request))
    assert reply.status_code == 200 and reply.json()["owner_id"] == owner
    if reason is None:
        assert reply.json() == client.post(BASE + "/reports", json=body()).json()
    else:
        assert reply.json() == {
            "schemaVersion": 1,
            "owner_id": owner,
            "unavailable": {
                "reason": reason,
                "reportId": "deposit_portfolio_summary",
                "sourceRevision": SOURCE_REVISION,
                "periodStart": "2026-11-01",
                "periodEnd": "2026-11-16",
            },
        }
    assert enabled.calls == []


def test_report_requirements_validate_shape_and_respect_existing_grants(
    enabled, monkeypatch
):
    client, _ = enabled.client(grant=False)
    base = {
        "source": "fictional_snapshot",
        "period_start": "2026-11-01",
        "period_end": "2026-11-16",
    }
    for requirement in (
        None,
        {},
        {**base, "source": "bank"},
        {**base, "period_start": "2026-11-20"},
        {**base, "period_start": "2026-02-31"},
        {**base, "period_start": "20261101"},
        {**base, "period_start": None},
        {**base, "period_end": None},
        {**base, "authority": "manager"},
    ):
        assert (
            client.post(
                BASE + "/reports", json=body(requirements=requirement)
            ).status_code
            == 422
        )
    monkeypatch.setattr(
        main.app.state, "bank_demo_policy", BankDemoPolicy(True, "teller")
    )
    request = body(
        report_id="liquidity_assumption_summary",
        requirements={"source": "institution_record"},
    )
    reply = client.post(BASE + "/reports", json=request)
    assert reply.status_code == 403 and "unavailable" not in reply.json()
    stale = client.post(
        BASE + "/reports",
        json=body(expected_source_revision="a" * 64, requirements=base),
    )
    assert stale.status_code == 409 and enabled.calls == []


@pytest.fixture
def enabled(world, monkeypatch):
    monkeypatch.setattr(
        main.app.state, "bank_demo_policy", BankDemoPolicy(True, "manager")
    )
    return world


def test_default_off_then_fictional_reports_need_no_analytical_grant_or_history(
    world, monkeypatch
):
    client, owner = world.client(grant=False)
    monkeypatch.setattr(main.app.state, "bank_demo_policy", BankDemoPolicy())
    assert client.get(BASE + "/context").status_code == 404
    monkeypatch.setattr(
        main.app.state, "bank_demo_policy", BankDemoPolicy(True, "manager")
    )
    before = client.get("/api/v1/chats").json()
    menu = client.get(BASE + "/context")
    assert menu.status_code == 200 and menu.json()["owner_id"] == owner
    assert len(menu.json()["reports"]) == 17
    for option in menu.json()["reports"]:
        result = client.post(BASE + "/reports", json=body(report_id=option["id"]))
        assert result.status_code == 200, result.text
        value = result.json()
        assert (
            value["owner_id"] == owner and value["result"]["title"] == option["label"]
        )
        assert (
            value["result"]["executionEnabled"] is False
            and len(result.content) <= 32768
        )
        assert (
            result.headers["cache-control"] == "no-store"
            and "cookie" in result.headers["vary"].lower()
        )
        assert result.headers.get("x-aqua-history-revision")
    assert client.get("/api/v1/chats").json() == before
    assert client.post("/api/v1/chats", json=world.body()).status_code == 403
    assert world.calls == []


def test_host_none_and_teller_are_closed_separate_from_app_dataset_grants(
    enabled, monkeypatch
):
    client, _ = enabled.client()
    monkeypatch.setattr(
        main.app.state, "bank_demo_policy", BankDemoPolicy(True, "none")
    )
    assert client.get(BASE + "/context").json()["reports"] == []
    assert client.post(BASE + "/reports", json=body()).status_code == 403
    monkeypatch.setattr(
        main.app.state, "bank_demo_policy", BankDemoPolicy(True, "teller")
    )
    assert len(client.get(BASE + "/context").json()["reports"]) == 2
    assert (
        client.post(
            BASE + "/reports", json=body(report_id="reconciliation_summary")
        ).status_code
        == 403
    )
    assert client.post(BASE + "/reports", json=body()).status_code == 200
    assert enabled.calls == []


def test_owner_binding_changes_with_account_and_never_accepts_client_roles(enabled):
    first, owner_a = enabled.client("A", grant=False)
    second, owner_b = enabled.client("B", grant=False)
    assert owner_a != owner_b
    assert first.get(BASE + "/context").json()["owner_id"] == owner_a
    assert second.post(BASE + "/reports", json=body()).json()["owner_id"] == owner_b
    for changes in (
        {"persona": "manager"},
        {"owner_id": owner_a},
        {"tenant": "bank"},
        {"schemaVersion": True},
        {"period": "2026-10"},
        {"report_id": "SELECT SECRET-CANARY"},
        {"expected_source_revision": "SECRET-CANARY"},
    ):
        response = first.post(BASE + "/reports", json=body(**changes))
        assert response.status_code == 422 and "SECRET-CANARY" not in response.text
    response = first.post(
        BASE + "/reports", json=body(expected_source_revision="a" * 64)
    )
    assert (
        response.status_code == 409
        and response.json()["error"]["code"] == "revision_conflict"
    )
    assert enabled.calls == []


@pytest.mark.parametrize(
    "encoding",
    ["duplicate", "escaped_duplicate", "utf16", "bom", "invalid_utf8", "nul", "padded"],
)
def test_raw_body_admission_is_bounded_unambiguous_utf8(enabled, encoding):
    client, _ = enabled.client()
    raw = json.dumps(body(), separators=(",", ":")).encode()
    status = 422
    if encoding == "duplicate":
        raw = raw[:-1] + b',"schemaVersion":1}'
    elif encoding == "escaped_duplicate":
        raw = raw[:-1] + b',"schema\\u0056ersion":1}'
    elif encoding == "utf16":
        raw = raw.decode().encode("utf-16")
    elif encoding == "bom":
        raw = b"\xef\xbb\xbf" + raw
    elif encoding == "invalid_utf8":
        raw += b"\xff"
    elif encoding == "nul":
        raw += b"\x00"
    else:
        raw = b" " * (8193 - len(raw)) + raw
        status = 413
    response = client.post(
        BASE + "/reports", content=raw, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == status and len(response.content) < 512
    assert enabled.calls == []


def test_media_query_csrf_and_revoked_account_fail_without_provider_calls(
    enabled, monkeypatch
):
    client, owner = enabled.client()
    assert (
        client.post(
            BASE + "/reports",
            content="SECRET-CANARY",
            headers={"Content-Type": "text/plain"},
        ).status_code
        == 415
    )
    assert client.get(BASE + "/context?persona=SECRET-CANARY").status_code == 422
    assert (
        client.post(BASE + "/reports?persona=SECRET-CANARY", json=body()).status_code
        == 422
    )
    assert (
        client.post(
            BASE + "/reports",
            json=body(),
            headers={"Origin": "https://foreign.invalid"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            BASE + "/reports", json=body(), headers={"X-CSRF-Token": "foreign"}
        ).status_code
        == 403
    )
    with enabled.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.sessions SET revoked_at=clock_timestamp() WHERE user_id=%s",
            (owner,),
        )
    assert client.get(BASE + "/context").status_code == 401
    assert client.post(BASE + "/reports", json=body()).status_code == 401
    monkeypatch.setattr(
        main.app.state, "retirement", SimpleNamespace(ready=False), raising=False
    )
    assert client.get(BASE + "/context").status_code == 503
    assert enabled.calls == []


def test_context_and_report_share_existing_durable_workspace_allowance(enabled):
    client, owner = enabled.client(grant=False)
    for _ in range(30):
        assert client.get(BASE + "/context").status_code == 200
        assert client.post(BASE + "/reports", json=body()).status_code == 200
    assert client.get(BASE + "/context").status_code == 429
    with enabled.storage.transaction() as conn:
        assert conn.execute(
            "SELECT hits FROM app.workspace_admission WHERE user_id=%s", (owner,)
        ).fetchone() == (60,)
    assert enabled.calls == []
