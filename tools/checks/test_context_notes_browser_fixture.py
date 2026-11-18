"""Behavioral pure notes bridge guards; no resources, providers or database."""

import argparse
import base64
from contextlib import redirect_stderr
from dataclasses import dataclass
import io
import json
from pathlib import Path
from types import SimpleNamespace
import sys
from unittest.mock import MagicMock, Mock, patch

import pytest

import context_notes_browser_backend as entry
import context_notes_browser_fixture as fixture
import p05_browser_host as host
import p05_browser_messages as messages
import p05_browser_worker as worker
import p10c_browser_backend as identity_entry
import p11a_browser_backend as export_entry
import p11b_browser_backend as deletion_entry

ORIGIN = "http://127.0.0.1:12345"
IMAGE = "sha256:" + "a" * 64
ID = "71000000-0000-4000-8000-000000000001"
PATH = fixture.NOTES


@pytest.mark.parametrize("module", [host, worker])
@pytest.mark.parametrize("value", [None, 0, 1, "true", {}, []])
def test_notes_mode_exact_boolean_before_any_import_or_resource(module, value):
    with (
        patch.object(host, "Resources") as resources,
        patch.object(worker, "guard_fixture") as guard,
        pytest.raises(ValueError),
    ):
        if module is host:
            module.host(ORIGIN, IMAGE, notes_fixture=value)
        else:
            module.worker(ORIGIN, notes_fixture=value)
    resources.assert_not_called()
    guard.assert_not_called()


@pytest.mark.parametrize("module", [host, worker])
@pytest.mark.parametrize(
    "flag",
    [
        "workspace_analysis",
        "bank_demo_fixture",
        "account_security_fixture",
        "account_identity_fixture",
        "personal_export_fixture",
        "personal_deletion_fixture",
    ],
)
def test_notes_mode_excludes_other_fixture_authority_before_setup(module, flag):
    with (
        patch.object(host, "Resources") as resources,
        patch.object(worker, "guard_fixture") as guard,
        pytest.raises(ValueError, match="fixture_notes_mode_invalid"),
    ):
        if module is host:
            module.host(ORIGIN, IMAGE, **{flag: True}, notes_fixture=True)
        else:
            module.worker(ORIGIN, **{flag: True}, notes_fixture=True)
    resources.assert_not_called()
    guard.assert_not_called()


def test_worker_rejects_analysis_factory_and_truthy_analysis_before_app_import():
    for changes in ({"analysis_factory": Mock()}, {"workspace_analysis": 1}):
        with (
            patch.object(worker, "guard_fixture") as guard,
            pytest.raises(ValueError, match="fixture_notes_mode_invalid"),
        ):
            worker.worker(ORIGIN, notes_fixture=True, **changes)
        guard.assert_not_called()


@pytest.mark.parametrize("module", [host, worker])
@pytest.mark.parametrize("schema", [6, 7, 8, 9, 11, True, 10.0, "10"])
def test_notes_requires_current_exact_schema10_before_setup(module, schema):
    with (
        patch.object(module, "fixture_schema", return_value=schema),
        patch.object(host, "Resources") as resources,
        patch.object(worker, "guard_fixture") as guard,
        pytest.raises(ValueError, match="fixture_schema10_required"),
    ):
        if module is host:
            module.host(ORIGIN, IMAGE, notes_fixture=True)
        else:
            module.worker(ORIGIN, notes_fixture=True)
    resources.assert_not_called()
    guard.assert_not_called()


@pytest.mark.parametrize("module", [host, worker])
@pytest.mark.parametrize(
    "origin",
    ["https://aqua-ai.us", "http://localhost:12345", "http://127.0.0.1:80"],
)
def test_notes_origin_cannot_target_a_real_or_ambiguous_service(module, origin):
    with (
        patch.object(host, "Resources") as resources,
        patch.object(worker, "guard_fixture") as guard,
        pytest.raises(ValueError, match="fixture_origin_invalid"),
    ):
        if module is host:
            module.host(origin, IMAGE, notes_fixture=True)
        else:
            module.worker(origin, notes_fixture=True)
    resources.assert_not_called()
    guard.assert_not_called()


def test_fixed_entrypoint_has_only_worker_origin_and_immutable_image():
    for selected in (False, True):
        args = entry.arguments(
            (["--worker"] if selected else []) + ["--origin", ORIGIN, "--image", IMAGE]
        )
        with (
            patch.object(entry, "host", return_value=0) as native,
            patch.object(entry.p05_browser_worker, "worker", return_value=0) as child,
        ):
            assert entry.run(args) == 0
        if selected:
            child.assert_called_once_with(ORIGIN, notes_fixture=True)
            native.assert_not_called()
        else:
            native.assert_called_once_with(ORIGIN, IMAGE, notes_fixture=True)
            child.assert_not_called()
    for name in ("--owner", "--dataset", "--scope", "--role", "--workspace-analysis"):
        with redirect_stderr(io.StringIO()), pytest.raises(SystemExit):
            entry.arguments(["--origin", ORIGIN, "--image", IMAGE, name, "value"])
    for image in ("aqua-runtime:check", "sha256:short", None, [], ""):
        with patch.object(entry, "host") as launch, pytest.raises(ValueError):
            entry.run(argparse.Namespace(worker=False, origin=ORIGIN, image=image))
        launch.assert_not_called()


def test_inherited_features_are_scrubbed_before_main_import_without_resources():
    class Stop(Exception):
        pass

    env = {
        "CONTEXT_NOTES_ENABLED": "invalid",
        "CONTEXT_NOTES_OWNER": "arbitrary",
        "COMPANION_ENABLED": "true",
        "BANK_DEMO_PERSONA": "manager",
        "DATABASE_URL": "private",
        "GEMINI_API_KEY": "private",
    }
    with (
        patch.dict(worker.os.environ, env, clear=True),
        patch.object(worker.sys, "path", []),
        patch.object(worker.logging, "disable"),
        patch.object(worker, "guard_fixture", side_effect=Stop),
        pytest.raises(Stop),
    ):
        try:
            worker.worker(ORIGIN, notes_fixture=True)
        finally:
            assert all(
                key not in worker.os.environ for key in env if key != "DATABASE_URL"
            )
            assert worker.os.environ["DATABASE_URL"] == ""


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", PATH),
        ("POST", PATH),
        ("GET", PATH + "/" + ID),
        ("PATCH", PATH + "/" + ID),
        ("POST", PATH + "/" + ID + "/forget"),
        ("POST", PATH + "/" + ID + "/prepare"),
        ("GET", "/api/auth/me"),
        ("GET", "/api/v1/companion/capabilities"),
        ("GET", "/api/v1/chats?limit=20&archived=false"),
        ("GET", "/api/v1/projects?limit=20"),
        ("GET", "/api/v1/me/saved-prompts?limit=20"),
        ("GET", "/api/v1/auth/bootstrap?action=login"),
        ("GET", "/api/v1/auth/bootstrap?action=registration"),
        ("GET", "/api/v1/auth/bootstrap?action=verification"),
        ("POST", "/api/v1/auth/password-login"),
        ("POST", "/api/auth/google"),
    ],
)
def test_closed_route_allows_only_reviewed_notes_auth_and_shell_forms(method, path):
    assert fixture.notes_route(path, method)


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/query"),
        ("GET", "/api/v1/analysis-requests/" + ID),
        ("POST", "/api/v1/chats"),
        ("POST", "/api/v1/chats/" + ID + "/messages"),
        ("POST", "/api/v1/chats/" + ID + "/messages/" + ID + "/retries"),
        ("POST", "/api/v1/companion/help"),
        ("POST", "/api/v1/companion/result-brief"),
        ("POST", "/api/v1/bank-demo/reports"),
        ("PATCH", "/api/v1/me/preferences"),
        ("GET", "/api/v1/unknown"),
        ("GET", "https://aqua-ai.us" + PATH),
        ("GET", "//other.invalid" + PATH),
        ("GET", PATH + "?owner=x"),
        ("GET", PATH + "#"),
        ("GET", PATH + "#x"),
        ("GET", PATH + "/%2e%2e/" + ID),
        ("GET", PATH + "/" + ID + "/more"),
        ("GET", PATH + "/" + ID.replace("710", "A10")),
        ("DELETE", PATH + "/" + ID),
        ("GET", PATH + "/" + ID + "/prepare"),
        ("POST", PATH + "/" + ID + "/execute"),
        ("GET", "/api/v1/chats?limit=20&limit=20"),
        ("GET", "/api/v1/chats?owner=x"),
        ("GET", "/api/v1/chats?limit=100"),
        ("GET", "/api/v1/chats?archived=1"),
        ("GET", "/api/v1/auth/bootstrap?action=reset"),
        ("GET", "/api/v1/auth/bootstrap?action=login&owner=x"),
        ("GET", "/api/v1/auth/bootstrap"),
        ("GET", PATH + "\n"),
        (None, PATH),
        ("GET", None),
    ],
)
def test_closed_routes_cannot_fall_through_to_general_workspace_authority(method, path):
    assert not fixture.notes_route(path, method)


@dataclass
class Settings:
    database_url: str = fixture.DATASET
    session_secret: str = "f" * 64


def setup():
    store = MagicMock()
    conn = store.transaction.return_value.__enter__.return_value
    with patch.dict(
        sys.modules, {"auth.config": SimpleNamespace(dataset_key=lambda _: "a" * 64)}
    ):
        notes = fixture.NotesFixture(store, Settings())
    return notes, conn


def request(path=PATH, method="GET", body=b"", headers=None):
    return {
        "id": 1,
        "kind": "request",
        "path": path,
        "method": method,
        "headers": headers or [],
        "bodyBase64": base64.b64encode(body).decode(),
    }


def test_closed_forwarding_preserves_real_cookie_csrf_history_body_and_response():
    notes, _ = setup()
    client = Mock()
    result = Mock(status_code=200, content=b'{"real":"private"}')
    result.headers.multi_items.return_value = [("cache-control", "no-store")]
    client.request.return_value = result
    raw = b'{"schemaVersion":1}'
    headers = [
        ["Cookie", "actual-browser-cookie"],
        ["X-CSRF-Token", "actual-csrf"],
        ["X-Aqua-History-Revision", "a" * 64],
        ["Host", "untrusted"],
    ]
    response = messages.dispatch(
        request(PATH, "POST", raw, headers),
        client,
        notes.storage,
        None,
        [],
        notes_fixture=notes,
    )
    assert response["status"] == 200
    assert base64.b64decode(response["bodyBase64"]) == result.content
    assert response["headers"] == [["cache-control", "no-store"]]
    client.request.assert_called_once_with(
        "POST",
        PATH,
        headers=[tuple(value) for value in headers[:-1]],
        content=raw,
        follow_redirects=False,
    )
    assert client.cookies.clear.call_count == 2
    notes.storage.transaction.assert_not_called()


def test_notes_denies_broad_routes_controls_extra_keys_before_any_client_or_sql():
    notes, _ = setup()
    client = Mock()
    for item in (
        request("/api/query", "POST"),
        request("/api/v1/chats", "POST"),
        {**request(), "owner_id": ID},
        {"id": 1, "kind": "recover_rates"},
        {"id": 1, "kind": "workspace_grant"},
        {"id": 1, "kind": "notes_grant", "dataset": "forged"},
    ):
        with pytest.raises(ValueError):
            notes.dispatch(item, client, notes.storage, None, [])
    client.request.assert_not_called()
    notes.storage.transaction.assert_not_called()
    assert notes.forbidden_requests == 5


@pytest.mark.parametrize(
    "identifier", [True, False, 0, -1, 1000001, [], {}, None, "", "x\n"]
)
def test_ambiguous_control_identifier_is_rejected_before_transaction(identifier):
    notes, _ = setup()
    with pytest.raises(ValueError, match="fixture_notes_identifier_invalid"):
        notes.dispatch(
            {"id": identifier, "kind": "notes_grant"}, Mock(), notes.storage, None, []
        )
    notes.storage.transaction.assert_not_called()


def test_original_http_body_header_response_caps_and_cookie_cleanup_are_retained():
    notes, _ = setup()
    client = Mock()
    for item in (
        request(PATH, "POST", b"x" * 16385),
        request(headers=[["X", "bad\r\nvalue"]]),
        {**request(), "bodyBase64": "!invalid"},
    ):
        with pytest.raises(ValueError):
            notes.dispatch(item, client, notes.storage, None, [])
    client.request.assert_not_called()
    response = Mock(status_code=200, content=b"x" * 16385)
    client.request.return_value = response
    with pytest.raises(ValueError, match="fixture_response_body_limit"):
        notes.dispatch(request(), client, notes.storage, None, [])
    assert client.cookies.clear.call_count == 2


def test_fixed_control_state_machine_has_no_replay_and_normal_grant_trigger_updates():
    notes, conn = setup()
    conn.execute.return_value.fetchone.return_value = (ID,)
    for kind in ("notes_revoke", "notes_regrant", "notes_history_advance"):
        with pytest.raises(ValueError, match="fixture_notes_control_order"):
            notes.control({"id": 1, "kind": kind})
    notes.storage.transaction.assert_not_called()
    for index, kind in enumerate(
        ["notes_grant", "notes_revoke", "notes_regrant", "notes_history_advance"]
    ):
        result = notes.control({"id": index + 1, "kind": kind})
        assert result == {
            "id": index + 1,
            "kind": kind,
            **({"advanced": True} if index == 3 else {"enabled": index != 1}),
        }
        before = notes.storage.transaction.call_count
        with pytest.raises(ValueError, match="fixture_notes_control_order"):
            notes.control({"id": index + 1, "kind": kind})
        assert notes.storage.transaction.call_count == before
    assert notes.state == "history_advanced"
    changes = [call.args for call in conn.execute.call_args_list][1::2]
    assert all(args[-1][0] == ID for args in changes)
    assert "revoked_at=clock_timestamp()" in changes[1][0]
    assert "revoked_at=NULL" in changes[2][0]
    assert "version=" not in changes[1][0] + changes[2][0]
    assert "history_generation=1" in changes[3][0]


def test_install_keeps_actual_analysis_lifecycle_but_supplies_fail_closed_engine(
    monkeypatch,
):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "backend"))
    notes, _ = setup()
    main = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    constructor = Mock(return_value=SimpleNamespace())
    with patch.dict(
        sys.modules,
        {
            "auth.config": SimpleNamespace(load_auth_policy=lambda _: "fixed-policy"),
            "analysis.service": SimpleNamespace(Analysis=constructor),
        },
    ):
        notes.install(main)
    assert constructor.call_args.kwargs == {"engine": notes.engine}
    assert constructor.call_args.args[0] is notes.storage
    assert constructor.call_args.args[3] is notes.settings
    assert main.app.state.context_notes_policy.enabled is True
    assert main.app.state.companion_policy.enabled is False
    assert main.app.state.bank_demo_policy.enabled is False
    assert main.app.state.analysis.enqueue == notes.no_enqueue
    assert main.app.state.analysis.legacy == notes.no_enqueue
    with pytest.raises(AssertionError):
        main.app.state.analysis.enqueue()
    with pytest.raises(AssertionError):
        main.get_schema()
    assert notes.enqueue_calls == notes.provider_calls == 1
    assert notes.engine.calls == 0


@pytest.mark.parametrize("module", [identity_entry, export_entry, deletion_entry])
@pytest.mark.parametrize("schema", [9, 11, True, 10.0, "10"])
def test_standalone_current_schema_gates_cannot_launch_old_or_ambiguous_source(
    module, schema
):
    with (
        patch.object(
            sys,
            "argv",
            [
                "fixture",
                "--origin",
                "https://aqua-browser.example.test",
                "--image",
                IMAGE,
            ],
        ),
        patch.object(module, "fixture_schema", return_value=schema),
        patch.object(module, "host") as native,
        patch.object(module.p05_browser_worker, "worker") as child,
        pytest.raises(ValueError),
    ):
        module.main()
    native.assert_not_called()
    child.assert_not_called()


@pytest.mark.parametrize("module", [identity_entry, export_entry, deletion_entry])
def test_standalone_exact_current_schema_reaches_only_fixed_host_mode(module):
    with (
        patch.object(
            sys,
            "argv",
            [
                "fixture",
                "--origin",
                "https://aqua-browser.example.test",
                "--image",
                IMAGE,
            ],
        ),
        patch.object(module, "fixture_schema", return_value=10),
        patch.object(module, "host", return_value=0) as native,
        patch.object(module.p05_browser_worker, "worker") as child,
    ):
        assert module.main() == 0
    native.assert_called_once()
    child.assert_not_called()
    assert native.call_args.args == ("https://aqua-browser.example.test", IMAGE, True)


def test_failed_or_replaced_fixed_owner_control_does_not_advance_state():
    notes, conn = setup()
    conn.execute.return_value.fetchone.return_value = None
    with pytest.raises(ValueError):
        notes.control({"id": 1, "kind": "notes_grant"})
    assert notes.state == "ungranted" and notes.owner is None
    notes.owner = ID
    conn.execute.return_value.fetchone.return_value = ("other",)
    with pytest.raises(ValueError):
        notes.control({"id": 1, "kind": "notes_grant"})
    assert notes.state == "ungranted"


def test_stats_are_actual_fixed_scope_counts_and_execution_attempt_instrumentation():
    notes, conn = setup()
    conn.execute.return_value.fetchall.return_value = [(ID,)]
    conn.execute.return_value.fetchone.side_effect = [(2,), (0,), (0,), (0,), (0,)] * 4
    first = notes.stats(1)
    assert first == {
        "id": 1,
        "kind": "notes_stats",
        "state": "ungranted",
        "notes": 2,
        "chats": 0,
        "messages": 0,
        "analysis": 0,
        "engine_calls": 0,
        "enqueue_calls": 0,
        "provider_calls": 0,
        "forbidden_requests": 0,
    }
    for call in (
        lambda: notes.engine.run({}, Mock()),
        notes.no_enqueue,
        notes.no_provider,
    ):
        with pytest.raises(AssertionError):
            call()
    second = notes.stats(2)
    assert (
        second["engine_calls"]
        == second["enqueue_calls"]
        == second["provider_calls"]
        == 1
    )
    notes.stats(3)
    notes.stats(4)
    before = notes.storage.transaction.call_count
    with pytest.raises(ValueError, match="fixture_notes_stats_limit"):
        notes.stats(5)
    assert notes.storage.transaction.call_count == before
    assert all(
        call.args[0].startswith("SELECT ") for call in conn.execute.call_args_list
    )
    assert not any(
        value in json.dumps(second) for value in (ID, fixture.DATASET, "cookie", "body")
    )


def test_mailbox_has_only_one_fixed_verification_read_and_no_clock_bypass():
    notes, _ = setup()
    item = {"id": 1, "kind": "mailbox", "purpose": "verify_email"}
    with patch.object(messages, "dispatch", return_value={"found": True}) as original:
        assert notes.dispatch(item, Mock(), notes.storage, None, []) == {"found": True}
        for changed in (
            item,
            {**item, "purpose": "reset_password"},
            {**item, "owner": ID},
        ):
            with pytest.raises(ValueError):
                notes.dispatch(changed, Mock(), notes.storage, None, [])
    original.assert_called_once()
    notes.storage.transaction.assert_not_called()


def host_case(ready):
    child = Mock(
        stdin=io.BytesIO(), stdout=io.BytesIO(json.dumps(ready).encode() + b"\n")
    )
    child.wait.return_value = 0
    resources = Mock()
    resources.provision.return_value = "synthetic-runner-id"
    resources.cleanup.return_value = []
    emitted = []
    with (
        patch.object(host, "Resources", return_value=resources),
        patch.object(host.subprocess, "Popen", return_value=child) as launch,
        patch.object(host, "message", return_value={"id": 2, "kind": "finish"}),
        patch.object(host, "emit", side_effect=emitted.append),
        patch.multiple(
            host.signal, SIGALRM=14, SIGHUP=1, signal=Mock(), alarm=Mock(), create=True
        ),
    ):
        code = host.host(ORIGIN, IMAGE, notes_fixture=True)
    resources.cleanup.assert_called_once()
    return code, emitted[-1], launch.call_args.args[0]


def readiness(**changes):
    return {
        "kind": "ready",
        "schema_version": 10,
        "origin": ORIGIN,
        "notes_fixture": True,
        "workspace_analysis_fixture": False,
        "dataset_grants": 0,
        "max_requests": 256,
        "max_seconds": 300,
        "body_bytes_max": 16384,
        "capabilities": {"workspace_analysis": False},
        **changes,
    }


def test_host_pins_only_notes_worker_original_caps_and_actual_cleanup():
    code, final, command = host_case(readiness())
    assert code == 0 and final["status"] == "passed"
    assert command[8] == "/checks/tools/checks/context_notes_browser_backend.py"
    assert command[-4:] == ["--origin", ORIGIN, "--image", IMAGE]
    assert final["report"]["max_operations"] == 256
    assert final["report"]["notes_fixture"] is True
    assert final["report"]["workspace_analysis_fixture"] is False
    assert final["report"]["cleanup"] == "removed_and_absence_confirmed"


@pytest.mark.parametrize(
    "change",
    [
        {"notes_fixture": False},
        {"notes_fixture": 1},
        {"schema_version": 9},
        {"schema_version": 10.0},
        {"origin": "https://aqua-ai.us"},
        {"capabilities": {"workspace_analysis": True}},
        {"capabilities": []},
        {"workspace_analysis_fixture": True},
        {"max_requests": 400},
        {"max_requests": 256.0},
        {"max_seconds": 301},
        {"body_bytes_max": 32768},
        {"dataset_grants": True},
        {"dataset_grants": 1},
    ],
)
def test_wrong_mode_schema_or_caps_cannot_qualify_even_with_cleanup(change):
    code, final, _ = host_case(readiness(**change))
    assert code == 1 and final["status"] == "failed"
    assert final["report"]["cleanup"] == "removed_and_absence_confirmed"
