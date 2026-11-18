"""Pure forwarding/mode/lifecycle guards; no Docker, HTTP listener or database."""

import argparse
import base64
from contextlib import redirect_stderr
import io
import json
from importlib.machinery import PathFinder
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import bank_demo_browser_backend as entry
import p05_browser_host as host
import p05_browser_messages as messages
import p05_browser_worker as worker

ORIGIN = "http://127.0.0.1:12345"
IMAGE = "sha256:" + "a" * 64


@pytest.mark.parametrize("module", [host, worker])
@pytest.mark.parametrize("value", [None, 0, 1, "true", {}, []])
def test_bank_mode_requires_an_exact_boolean_before_any_resources(module, value):
    with (
        patch.object(host, "Resources") as resources,
        patch.object(worker, "guard_fixture") as guard,
    ):
        with pytest.raises(ValueError):
            if module is host:
                module.host(ORIGIN, IMAGE, bank_demo_fixture=value)
            else:
                module.worker(ORIGIN, bank_demo_fixture=value)
        resources.assert_not_called()
        guard.assert_not_called()


@pytest.mark.parametrize("module", [host, worker])
@pytest.mark.parametrize(
    "flag",
    [
        "workspace_analysis",
        "account_security_fixture",
        "account_identity_fixture",
        "personal_export_fixture",
        "personal_deletion_fixture",
    ],
)
def test_bank_mode_cannot_combine_with_another_fixture_authority(module, flag):
    with (
        patch.object(host, "Resources") as resources,
        patch.object(worker, "guard_fixture") as guard,
    ):
        with pytest.raises(ValueError, match="fixture_bank_demo_mode_invalid"):
            if module is host:
                module.host(ORIGIN, IMAGE, **{flag: True}, bank_demo_fixture=True)
            else:
                module.worker(ORIGIN, **{flag: True}, bank_demo_fixture=True)
        resources.assert_not_called()
        guard.assert_not_called()


def test_bank_worker_rejects_an_analysis_factory_before_import_or_setup():
    with (
        patch.object(worker, "guard_fixture") as guard,
        pytest.raises(ValueError, match="fixture_bank_demo_mode_invalid"),
    ):
        worker.worker(ORIGIN, analysis_factory=Mock(), bank_demo_fixture=True)
    guard.assert_not_called()


@pytest.mark.parametrize("bank", [False, True])
def test_actual_worker_prefix_resolves_shared_pure_data_only_in_fixed_bank_mode(bank):
    class GuardStop(Exception):
        pass

    paths = [str(worker.ROOT / "tools/checks")]
    with (
        patch.object(worker, "sys", SimpleNamespace(path=paths)),
        patch.dict(
            worker.os.environ,
            {"BANK_DEMO_PERSONA": "manager", "COMPANION_ENABLED": "true"},
            clear=True,
        ),
        patch.object(worker.logging, "disable"),
        patch.object(worker, "guard_fixture", side_effect=GuardStop),
        patch.object(worker, "WORKER_STAGE", "before_start"),
        pytest.raises(GuardStop),
    ):
        worker.worker(ORIGIN, bank_demo_fixture=bank)
    assert paths[0] == str(worker.ROOT / "backend")
    shared = PathFinder.find_spec("mcp_demo", paths)
    assert (shared is not None) is bank
    assert (str(worker.ROOT) in paths) is bank
    if bank:
        assert paths[1] == str(worker.ROOT)
        assert shared.origin == str(worker.ROOT / "mcp_demo/__init__.py")


@pytest.mark.parametrize("module", [host, worker])
@pytest.mark.parametrize(
    "origin",
    [
        "https://aqua-ai.us",
        "http://localhost:12345",
        "http://127.0.0.1:80",
        "http://127.0.0.1:12345/private",
    ],
)
def test_bank_mode_cannot_redirect_its_origin_before_any_native_setup(module, origin):
    with (
        patch.object(host, "Resources") as resources,
        patch.object(worker, "guard_fixture") as guard,
    ):
        with pytest.raises(ValueError, match="fixture_origin_invalid"):
            if module is host:
                module.host(origin, IMAGE, bank_demo_fixture=True)
            else:
                module.worker(origin, bank_demo_fixture=True)
        resources.assert_not_called()
        guard.assert_not_called()


@pytest.mark.parametrize("module", [host, worker])
@pytest.mark.parametrize("schema", [6, 7, 8, 9, 11, True, 10.0, "10"])
def test_bank_mode_retains_exact_schema10_before_resources_or_app_import(
    module, schema
):
    with (
        patch.object(module, "fixture_schema", return_value=schema),
        patch.object(host, "Resources") as resources,
        patch.object(worker, "guard_fixture") as guard,
    ):
        with pytest.raises(ValueError, match="fixture_schema10_required"):
            if module is host:
                module.host(ORIGIN, IMAGE, bank_demo_fixture=True)
            else:
                module.worker(ORIGIN, bank_demo_fixture=True)
        resources.assert_not_called()
        guard.assert_not_called()


def test_fixed_entrypoint_has_no_role_scope_or_analytical_switch():
    with patch.object(entry, "host", return_value=0) as launch:
        assert entry.run(entry.arguments(["--origin", ORIGIN, "--image", IMAGE])) == 0
    launch.assert_called_once_with(ORIGIN, IMAGE, bank_demo_fixture=True)
    with patch.object(entry.p05_browser_worker, "worker", return_value=0) as launch:
        assert (
            entry.run(
                entry.arguments(["--worker", "--origin", ORIGIN, "--image", IMAGE])
            )
            == 0
        )
    launch.assert_called_once_with(ORIGIN, bank_demo_fixture=True)
    for name in ["--persona", "--tenant", "--scope", "--workspace-analysis"]:
        with redirect_stderr(io.StringIO()), pytest.raises(SystemExit):
            entry.arguments(["--origin", ORIGIN, "--image", IMAGE, name, "manager"])
    for image in ["aqua-runtime:check", "sha256:short", "ssh://host", ""]:
        with patch.object(entry, "host") as launch, pytest.raises(ValueError):
            entry.run(argparse.Namespace(worker=False, origin=ORIGIN, image=image))
        launch.assert_not_called()


def request(path, method="GET", body=b"", headers=None):
    return {
        "id": 1,
        "kind": "request",
        "method": method,
        "path": path,
        "headers": headers or [],
        "bodyBase64": base64.b64encode(body).decode(),
    }


def test_only_two_bank_routes_and_existing_help_capability_read_are_added():
    client = Mock()
    response = Mock(status_code=200, content=b'{"synthetic":true}')
    response.headers.multi_items.return_value = [("content-type", "application/json")]
    client.request.return_value = response
    for method, path in [
        ("GET", "/api/v1/bank-demo/context"),
        ("POST", "/api/v1/bank-demo/reports"),
        ("GET", "/api/v1/companion/capabilities"),
    ]:
        item = request(
            path,
            method,
            b"{}",
            [["Cookie", "synthetic-cookie"], ["Host", "not-forwarded"]],
        )
        with pytest.raises(ValueError, match="fixture_request_invalid"):
            messages.dispatch(item, client, None, Mock(), [])
        client.request.assert_not_called()
        value = messages.dispatch(
            item, client, None, Mock(), [], bank_demo_fixture=True
        )
        assert value["status"] == 200
        assert base64.b64decode(value["bodyBase64"]) == response.content
        args, kwargs = client.request.call_args
        assert args == (method, path)
        assert kwargs["headers"] == [("Cookie", "synthetic-cookie")]
        assert kwargs["follow_redirects"] is False
        assert client.cookies.clear.call_count >= 2
        client.reset_mock()
    for method, path in [
        ("POST", "/api/v1/bank-demo/context"),
        ("GET", "/api/v1/bank-demo/reports"),
        ("GET", "/api/v1/bank-demo/context?persona=manager"),
        ("GET", "/api/v1/bank-demo/context/extra"),
        ("POST", "/api/v1/bank-demo/execute"),
        ("GET", "https://aqua-ai.us/api/v1/bank-demo/context"),
        ("POST", "/api/v1/companion/capabilities"),
        ("POST", "/api/v1/companion/help"),
        ("GET", "/api/v1/companion/capabilities?role=manager"),
    ]:
        with pytest.raises(ValueError, match="fixture_request_invalid"):
            messages.dispatch(
                request(path, method), client, None, Mock(), [], bank_demo_fixture=True
            )
        client.request.assert_not_called()


def test_bank_forwarding_keeps_original_body_header_and_cookie_boundaries():
    client = Mock()
    for item in [
        request("/api/v1/bank-demo/reports", "POST", b"x" * 16385),
        request("/api/v1/bank-demo/context", headers=[["Cookie", "bad\r\nvalue"]]),
    ]:
        with pytest.raises(ValueError):
            messages.dispatch(item, client, None, Mock(), [], bank_demo_fixture=True)
        client.request.assert_not_called()
    with pytest.raises(ValueError, match="fixture_bank_demo_mode_invalid"):
        messages.dispatch(
            request("/api/v1/bank-demo/context"),
            client,
            None,
            Mock(),
            [],
            bank_demo_fixture=1,
        )


@pytest.mark.parametrize("bank", [False, True])
def test_host_routes_only_the_opt_in_to_its_fixed_worker_and_retains_256_operations(
    bank,
):
    ready = {"kind": "ready", "schema_version": 10}
    if bank:
        ready.update(bank_demo_fixture=True, bank_demo_persona="teller")
    child = Mock(
        stdin=io.BytesIO(), stdout=io.BytesIO(json.dumps(ready).encode() + b"\n")
    )
    child.wait.return_value = 0
    resources = Mock()
    resources.provision.return_value = "synthetic-runner-id"
    resources.cleanup.return_value = []
    emitted = []
    with (
        patch.object(host, "fixture_schema", return_value=10),
        patch.object(host, "Resources", return_value=resources),
        patch.object(host.signal, "SIGALRM", 14, create=True),
        patch.object(host.signal, "SIGHUP", 1, create=True),
        patch.object(host.signal, "signal"),
        patch.object(host.signal, "alarm", create=True),
        patch.object(host.subprocess, "Popen", return_value=child) as popen,
        patch.object(host, "message", return_value={"id": "finish", "kind": "finish"}),
        patch.object(host, "emit", side_effect=emitted.append),
    ):
        assert host.host(ORIGIN, IMAGE, bank_demo_fixture=bank) == 0
    argv = popen.call_args.args[0]
    assert argv[8] == (
        "/checks/tools/checks/bank_demo_browser_backend.py"
        if bank
        else "/checks/tools/checks/p05_browser_backend.py"
    )
    assert ("--image" in argv) is bank
    report = emitted[-1]["report"]
    assert report["max_operations"] == 256
    assert report["workspace_analysis_fixture"] is False
    assert ("bank_demo_fixture" in report) is bank
    assert report["provider_calls"] == 0
    assert report["cleanup"] == "removed_and_absence_confirmed"
    resources.cleanup.assert_called_once()


@pytest.mark.parametrize(
    "ready",
    [
        {"bank_demo_fixture": False},
        {"bank_demo_fixture": 1, "bank_demo_persona": "teller"},
        {"bank_demo_fixture": True, "bank_demo_persona": "manager"},
    ],
)
def test_wrong_mode_or_persona_readiness_stops_with_owned_cleanup(ready):
    child = Mock(
        stdin=io.BytesIO(),
        stdout=io.BytesIO(
            json.dumps({"kind": "ready", "schema_version": 10, **ready}).encode()
            + b"\n"
        ),
    )
    child.wait.return_value = 0
    resources = Mock()
    resources.provision.return_value = "synthetic-runner-id"
    resources.cleanup.return_value = []
    emitted = []
    with (
        patch.object(host, "fixture_schema", return_value=10),
        patch.object(host, "Resources", return_value=resources),
        patch.object(host.signal, "SIGALRM", 14, create=True),
        patch.object(host.signal, "SIGHUP", 1, create=True),
        patch.object(host.signal, "signal"),
        patch.object(host.signal, "alarm", create=True),
        patch.object(host.subprocess, "Popen", return_value=child),
        patch.object(host, "emit", side_effect=emitted.append),
    ):
        assert host.host(ORIGIN, IMAGE, bank_demo_fixture=True) == 1
    resources.cleanup.assert_called_once()
    assert emitted[-1]["status"] == "failed"
    assert emitted[-1]["report"]["cleanup"] == "removed_and_absence_confirmed"
