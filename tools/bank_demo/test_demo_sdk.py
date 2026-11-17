"""Actual SDK/stdio boundaries using fictional inputs and disposable child processes."""

import os
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import anyio
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp_types import CLIENT_CAPABILITIES_META_KEY, PROTOCOL_VERSION_META_KEY

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp_demo import data  # noqa: E402
from mcp_demo.protocol import MAX_FRAME_BYTES  # noqa: E402
from mcp_demo.protocol import actor_for  # noqa: E402
from mcp_demo.server import build_server  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CANARY = "FICTIONAL_PRIVATE_INPUT_9681"


def child_environment():
    # No provider keys, bank credentials or model configuration go to test children.
    result = {
        name: os.environ[name]
        for name in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH")
        if name in os.environ
    }
    result.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    return result


def parameters(persona=None):
    arguments = ["-B", "-m", "mcp_demo"]
    if persona is not None:
        arguments += ["--persona", persona]
    return StdioServerParameters(
        command=sys.executable,
        args=arguments,
        cwd=str(ROOT),
        env=child_environment(),
    )


def modern_context_request():
    return (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "demo_context",
                    "arguments": {},
                    "_meta": {
                        PROTOCOL_VERSION_META_KEY: "2026-07-28",
                        CLIENT_CAPABILITIES_META_KEY: {},
                    },
                },
            }
        ).encode()
        + b"\n"
    )


def ready_reply(child):
    """Wait for a bounded real SDK response; kill before joining a stuck reader."""
    child.stdin.write(modern_context_request())
    child.stdin.flush()
    with ThreadPoolExecutor(max_workers=1) as readers:
        future = readers.submit(child.stdout.readline, MAX_FRAME_BYTES + 1)
        try:
            raw = future.result(timeout=3)
        except BaseException:
            child.kill()
            child.communicate(timeout=2)
            raise
    if len(raw) > MAX_FRAME_BYTES or not raw.endswith(b"\n"):
        raise AssertionError("bounded SDK readiness response missing")
    value = json.loads(raw)
    body = value.get("result", {}).get("structuredContent", {})
    if value.get("id") != 1 or body.get("synthetic") is not True:
        raise AssertionError("SDK context readiness response invalid")
    return raw


class DemoSdkTests(unittest.TestCase):
    def run_async(self, action):
        async def bounded():
            with anyio.fail_after(10):
                await action()

        anyio.run(bounded)

    def test_modern_and_legacy_clients_discover_and_call_real_stdio_server(self):
        async def check():
            for mode in ("2026-07-28", "legacy"):
                async with Client(parameters("analyst"), mode=mode) as client:
                    listed = await client.list_tools()
                    self.assertEqual(len(listed.tools), 7)
                    for tool in listed.tools:
                        self.assertTrue(tool.annotations.read_only_hint)
                        self.assertFalse(tool.annotations.destructive_hint)
                        self.assertFalse(tool.annotations.open_world_hint)
                    result = await client.call_tool("demo_context", {})
                    self.assertFalse(result.is_error)
                    body = result.structured_content
                    self.assertTrue(body["synthetic"] and body["demo_only"])
                    self.assertEqual(body["sourceRevision"], data.SOURCE_REVISION)
                    self.assertEqual(body["data"]["persona"], "analyst")
                    self.assertFalse(body["execution_enabled"])
                    self.assertFalse(body["approval_recorded"])
                    # Legacy hosts also receive a complete JSON text projection.
                    self.assertIn(data.SOURCE_REVISION, result.content[0].text)

        self.run_async(check)

    def test_default_scope_and_per_call_authority_claims_cannot_grant_access(self):
        async def check():
            async with Client(parameters()) as client:
                listed = await client.list_tools()
                self.assertEqual([tool.name for tool in listed.tools], ["demo_context"])
                for name, arguments in (
                    ("demo_context", {"persona": "manager", "claim": CANARY}),
                    ("run_demo_report", {"report_id": "reconciliation_summary"}),
                    ("approve_proposal", {"approved": True, "note": CANARY}),
                ):
                    result = await client.call_tool(name, arguments)
                    self.assertTrue(result.is_error)
                    self.assertNotIn(CANARY, result.model_dump_json())
                context = await client.call_tool("demo_context", {})
                self.assertEqual(context.structured_content["data"]["persona"], "none")

        self.run_async(check)

    def test_strict_args_redact_inputs_and_valid_call_recovers(self):
        async def check():
            async with Client(parameters("analyst")) as client:
                base = {
                    "currency": "USD",
                    "principal_usd": "1000.00",
                    "annual_rate_percent": "6",
                    "term_months": "12",
                }
                invalid = (
                    ("demo_context", {"unexpected": CANARY}),
                    ("run_demo_report", {"report_id": CANARY}),
                    ("search_demo_guidance", {"query": CANARY, "limit": True}),
                    (
                        "calculate_finance",
                        {
                            "operation": "simple_interest",
                            "parameters": dict(base, principal_usd=1000.0),
                        },
                    ),
                    (
                        "prepare_review_proposal",
                        {
                            "report_id": "reconciliation_summary",
                            "expected_source_revision": "0" * 64,
                            "note": CANARY,
                        },
                    ),
                )
                for name, arguments in invalid:
                    result = await client.call_tool(name, arguments)
                    self.assertTrue(result.is_error)
                    self.assertNotIn(CANARY, result.model_dump_json())
                    self.assertEqual(
                        result.structured_content["data"]["reason"],
                        "demo_request_denied",
                    )
                valid = await client.call_tool(
                    "calculate_finance",
                    {"operation": "simple_interest", "parameters": base},
                )
                self.assertFalse(valid.is_error)
                self.assertEqual(
                    valid.structured_content["data"]["status"], "calculated"
                )

        self.run_async(check)

    def raw_child(self, payload):
        with subprocess.Popen(
            [sys.executable, "-B", "-m", "mcp_demo", "--persona", "analyst"],
            cwd=ROOT,
            env=child_environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ) as child:
            try:
                output, errors = child.communicate(payload, timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.communicate(timeout=2)
                self.fail("bounded malformed-frame child did not exit after input EOF")
            self.assertIsNotNone(child.poll())
            self.assertLessEqual(len(output), MAX_FRAME_BYTES)
            self.assertLessEqual(len(errors), 8192)
            self.assertNotIn(CANARY.encode(), output + errors)
            self.assertNotIn(b"Traceback", errors)
            return child.returncode, output, errors

    def test_late_synchronous_result_is_denied_without_claiming_preemption(self):
        def delayed_dispatch(*arguments):
            time.sleep(0.03)
            return {"status": "late_success_must_not_escape"}

        async def check():
            async with Client(build_server(actor_for("analyst"))) as client:
                with (
                    patch("mcp_demo.server.HANDLER_SECONDS", 0.01),
                    patch("mcp_demo.server._dispatch", delayed_dispatch),
                ):
                    result = await client.call_tool("demo_context", {})
                self.assertTrue(result.is_error)
                self.assertEqual(
                    result.structured_content["data"]["reason"], "demo_deadline"
                )
                self.assertNotIn(
                    "late_success_must_not_escape", result.model_dump_json()
                )

        self.run_async(check)

    def test_malformed_utf8_oversized_and_unterminated_eof_frames_fail_closed(self):
        for payload in (
            b"\xff\n",
            CANARY.encode() + b"x" * MAX_FRAME_BYTES,
            CANARY.encode(),  # EOF before newline is not a complete SDK frame.
            ('{"unexpected":"' + CANARY + '"}\n').encode(),
        ):
            with self.subTest(kind=payload[:1], length=len(payload)):
                _, output, _ = self.raw_child(payload)
                self.assertNotIn(b'"synthetic":true', output)

    def test_duplicate_escaped_duplicate_and_depth_budget_deny_before_dispatch(self):
        for payload in (
            b'{"jsonrpc":"2.0","id":2,"method":"ping","method":"tools/list"}\n',
            b'{"jsonrpc":"2.0","id":2,"method":"ping","metho\\u0064":"tools/list"}\n',
            b'{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"demo_context","arguments":{"a":1,"\\u0061":2}}}\n',
            b'{"jsonrpc":"2.0","id":2,"method":"ping","params":{"deep":'
            + b"[" * 33
            + b"0"
            + b"]" * 33
            + b"}}\n",
            b'{"jsonrpc":"2.0","id":2,"method":"ping","params":{"wide":['
            + b",".join([b"0"] * 4097)
            + b"]}}\n",
            b'{"jsonrpc":"2.0","id":' + b"1" * 65 + b',"method":"ping"}\n',
            b'{"jsonrpc":"2.0","id":2,"method":"ping","params":{"value":NaN}}\n',
            b'{"jsonrpc":"2.0","id":2,"method":"ping","params":{"value":1e400}}\n',
        ):
            with self.subTest(length=len(payload)):
                code, output, errors = self.raw_child(payload)
                self.assertNotEqual(code, 0)
                self.assertEqual(output, b"")
                self.assertIn(b"invalid configuration, request or transport", errors)

    def test_negotiation_canaries_never_reach_sdk_reflection_errors(self):
        for request in (
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "ping",
                "params": {
                    "_meta": {
                        PROTOCOL_VERSION_META_KEY: CANARY,
                        CLIENT_CAPABILITIES_META_KEY: {},
                    }
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "initialize",
                "params": {
                    "protocolVersion": CANARY,
                    "capabilities": {},
                    "clientInfo": {"name": "synthetic-probe", "version": "1"},
                },
            },
        ):
            payload = json.dumps(request).encode() + b"\n"
            with self.subTest(method=request["method"]):
                code, output, _ = self.raw_child(payload)
                self.assertNotEqual(code, 0)
                self.assertEqual(output, b"")
        # Confirm the second SDK reflection path after a real modern ready barrier.
        with subprocess.Popen(
            [sys.executable, "-B", "-m", "mcp_demo"],
            cwd=ROOT,
            env=child_environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ) as child:
            ready_reply(child)
            output, errors = child.communicate(payload, timeout=5)
            self.assertNotEqual(child.returncode, 0)
            self.assertEqual(output, b"")
            self.assertNotIn(CANARY.encode(), output + errors)
            self.assertLessEqual(len(errors), 8192)

    def test_host_can_terminate_child_waiting_for_an_incomplete_local_frame(self):
        # A local stdio host owns process lifetime. No idle timeout is claimed.
        with subprocess.Popen(
            [sys.executable, "-B", "-m", "mcp_demo"],
            cwd=ROOT,
            env=child_environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ) as child:
            ready_reply(child)
            child.stdin.write(b'{"jsonrpc":')
            child.stdin.flush()
            child.terminate()
            try:
                output, errors = child.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.communicate(timeout=2)
                self.fail("stdio child remained after host termination")
            self.assertIsNotNone(child.poll())
            self.assertLessEqual(len(output) + len(errors), 8192)


if __name__ == "__main__":
    unittest.main()
