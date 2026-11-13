"""Reject ambiguous or oversized browser transport before identity work."""

import json

import pytest

from _auth_test_helpers import CLIENT_ID
from _durable_route_helpers import TOKEN, challenge

BASE = "/api/auth/google/redirect"
BODY = {"credential": TOKEN, "g_csrf_token": "synthetic-google-csrf"}


@pytest.mark.parametrize(
    "attack",
    [
        "duplicate_json",
        "duplicate_form",
        "unknown",
        "missing",
        "list",
        "number",
        "empty",
        "oversized_credential",
        "oversized_body",
        "mime",
        "bad_percent",
        "html",
        "client",
        "query",
        "foreign_origin",
        "null_origin",
    ],
)
def test_invalid_transport_has_no_authority(durable_browser, monkeypatch, attack):
    monkeypatch.setenv("GOOGLE_REDIRECT_ENABLED", "true")
    client, _, verified, _ = durable_browser
    challenge(durable_browser)
    body = dict(BODY)
    outgoing = {"Content-Type": "application/json"}
    path = BASE
    expected = 400
    if attack == "duplicate_json":
        raw = json.dumps(body)[:-1] + ',"credential":"other"}'
    elif attack == "duplicate_form":
        raw = "credential=one&credential=two&g_csrf_token=csrf"
        outgoing["Content-Type"] = "application/x-www-form-urlencoded"
    elif attack == "bad_percent":
        raw = "credential=%ZZ&g_csrf_token=csrf"
        outgoing["Content-Type"] = "application/x-www-form-urlencoded"
    else:
        if attack == "unknown":
            body["redirect_uri"] = "https://attacker.example"
        elif attack == "missing":
            body.pop("g_csrf_token")
        elif attack == "list":
            body = []
        elif attack == "number":
            body["credential"] = 17
        elif attack == "empty":
            body["credential"] = ""
        elif attack == "oversized_credential":
            body["credential"] = "a" * 8193
        elif attack == "oversized_body":
            body["credential"] = "a" * 17000
            expected = 413
        elif attack == "mime":
            outgoing["Content-Type"] = "text/plain"
        elif attack == "html":
            body["credential"] = "</script>PRIVATE"
        elif attack == "client":
            body["client_id"] = CLIENT_ID + "wrong"
        elif attack == "query":
            path += "?return_to=https://attacker.example"
        elif attack in {"foreign_origin", "null_origin"}:
            outgoing["Origin"] = (
                "https://attacker.example" if attack == "foreign_origin" else "null"
            )
            expected = 403
        raw = json.dumps(body)
    result = client.post(path, content=raw, headers=outgoing)
    assert result.status_code == expected
    assert verified == [] and "PRIVATE" not in result.text
    assert "attacker.example" not in result.text and "set-cookie" not in result.headers


@pytest.mark.parametrize(
    "attack",
    ["missing_challenge", "missing_google", "duplicate_challenge", "foreign_origin"],
)
def test_read_only_state_needs_unambiguous_first_party_binding(
    durable_browser, monkeypatch, attack
):
    monkeypatch.setenv("GOOGLE_REDIRECT_ENABLED", "true")
    client, _, verified, _ = durable_browser
    _, binding = challenge(durable_browser)
    client.cookies.set("g_csrf_token", BODY["g_csrf_token"])
    outgoing = {}
    if attack == "missing_challenge":
        client.cookies.clear()
    elif attack == "missing_google":
        client.cookies.delete("g_csrf_token")
    elif attack == "duplicate_challenge":
        outgoing["Cookie"] = (
            f"__Host-aqua_login={binding}; __Host-aqua_login={binding}; g_csrf_token=csrf"
        )
    else:
        outgoing["Origin"] = "https://attacker.example"
    response = client.get(BASE + "-state", headers=outgoing)
    assert response.status_code == 403 and verified == []
    assert "set-cookie" not in response.headers
