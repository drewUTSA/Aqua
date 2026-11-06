"""Pure closed-route/mode guards; never open Docker, databases or providers."""

import base64
import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from p11b_browser_authority import ROLES, dsn, provision
from p11b_browser_fixture import deletion_route, question_body
import p05_browser_host as host
import p05_browser_worker as worker

INTENT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
PATH = "/api/v1/me/data-deletions"


def test_only_closed_same_origin_post_deletion_routes_are_forwardable():
    assert deletion_route(PATH, "POST")
    assert deletion_route(PATH + "/by-intent/" + INTENT, "POST")
    for path in [
        "https://aqua-ai.us" + PATH,
        "//example.invalid" + PATH,
        PATH + "?owner=x",
        PATH + "#x",
        PATH + "/by-intent/../x",
        PATH + "/by-intent/" + INTENT + "/more",
        PATH + "/by-intent/" + INTENT.upper(),
        PATH + "\n",
    ]:
        assert not deletion_route(path, "POST")
    for method in ["GET", "PUT", "PATCH", "DELETE", None]:
        assert not deletion_route(PATH, method)


def test_only_two_bounded_synthetic_questions_can_reach_the_real_chat_route():
    def body(**changes):
        value = {
            "question": "P08 chart primitives",
            "model": "ollama",
            "client_request_id": INTENT,
            **changes,
        }
        return {"bodyBase64": base64.b64encode(json.dumps(value).encode()).decode()}

    question_body(body())
    question_body(body(question="P08 text explanation"))
    for changes in [
        {"question": "arbitrary"},
        {"model": "provider"},
        {"client_request_id": "../x"},
        {"owner": INTENT},
    ]:
        with pytest.raises(ValueError):
            question_body(body(**changes))
    with pytest.raises(ValueError):
        question_body({"bodyBase64": base64.b64encode(b"x" * 16385).decode()})


@pytest.mark.parametrize("module", [host, worker])
@pytest.mark.parametrize(
    "changes",
    [
        {"account_security_fixture": False},
        {"account_identity_fixture": False},
        {"personal_export_fixture": True},
        {"personal_deletion_fixture": "true"},
    ],
)
def test_schema9_deletion_mode_rejects_incomplete_or_ambiguous_fixture_modes(
    module, changes
):
    flags = {
        "account_security_fixture": True,
        "account_identity_fixture": True,
        "personal_deletion_fixture": True,
        **changes,
    }
    with (
        patch.object(module, "fixture_schema", return_value=9),
        pytest.raises(ValueError),
    ):
        if module is host:
            module.host(
                "https://aqua-browser.example.test", "sha256:" + "a" * 64, True, **flags
            )
        else:
            module.worker("https://aqua-browser.example.test", True, **flags)


def test_authority_connections_and_hba_remain_fixed_socket_roles_only():
    for role in ROLES:
        assert (
            dsn(role)
            == "host=/run/aqua-app-db port=5432 dbname=aqua_retirement user="
            + role
            + " password=fixture-only sslmode=disable"
        )
    for role in ["postgres", "aqua_app_runtime", "other@remote", None]:
        with pytest.raises(ValueError):
            dsn(role)
    calls = []
    root = Path(__file__).resolve().parents[2]
    provision(
        lambda *args, **kwargs: calls.append((args, kwargs)),
        "aqua-p05-browser-" + "a" * 24 + "-pg",
        root,
    )
    assert len(calls) == 4
    hba = calls[2][1]["data"].decode()
    assert hba.endswith(
        "local all all reject\nhost all all 0.0.0.0/0 reject\nhost all all ::/0 reject\n"
    )
    assert "host=" not in hba and "trust" not in hba


@pytest.mark.parametrize("module", [host, worker])
@pytest.mark.parametrize("schema", [6, 7, 8, 10, True])
def test_deletion_mode_never_admits_an_old_unknown_or_boolean_schema(module, schema):
    flags = {
        "account_security_fixture": True,
        "account_identity_fixture": True,
        "personal_deletion_fixture": True,
    }
    with (
        patch.object(module, "fixture_schema", return_value=schema),
        pytest.raises(ValueError),
    ):
        if module is host:
            module.host(
                "https://aqua-browser.example.test", "sha256:" + "a" * 64, True, **flags
            )
        else:
            module.worker("https://aqua-browser.example.test", True, **flags)
