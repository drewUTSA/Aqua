"""Real SDK stdio cancellation/admission with one synthetic awaitable gate."""

from pathlib import Path
import sys
import unittest

import anyio
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp_types import LoggingMessageNotification, LoggingMessageNotificationParams

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp_demo.protocol import actor_for  # noqa: E402
from tools.bank_demo.test_demo_sdk import ROOT, child_environment  # noqa: E402


async def blocking_fixture():
    """Test child only: use the real server, adding one cancellable slow handler."""
    from mcp_demo import server

    actual_build = server.build_server

    def build(actor):
        instance = actual_build(actor)
        admitted = False

        async def gate(context, call_next):
            nonlocal admitted
            if context.method == "tools/call" and not admitted:
                admitted = True
                # A fixed test notification is the admission barrier. No input
                # or product data is sent to logs; production has no such gate.
                await context.session.send_notification(
                    LoggingMessageNotification(
                        params=LoggingMessageNotificationParams(
                            level="info", data="synthetic_gate_entered"
                        )
                    ),
                    related_request_id=context.request_id,
                )
                await anyio.sleep_forever()
            return await call_next(context)

        instance.middleware.append(gate)
        return instance

    server.build_server = build
    await server.run_stdio(actor_for("analyst"))


class DemoCancellationTests(unittest.TestCase):
    def test_actual_stdio_cancel_releases_admission_and_recovers_before_deadline(self):
        async def check_mode(mode):
            entered, finished = anyio.Event(), anyio.Event()
            scopes, returned = [], []

            async def logged(params):
                if params.data == "synthetic_gate_entered":
                    entered.set()

            params = StdioServerParameters(
                command=sys.executable,
                args=["-B", str(Path(__file__).resolve()), "--blocking-fixture"],
                cwd=str(ROOT),
                env=child_environment(),
            )
            async with Client(
                params, mode=mode, logging_callback=logged, log_level="info"
            ) as client:
                self.assertEqual(len((await client.list_tools()).tools), 7)

                async def first_request():
                    try:
                        with anyio.CancelScope() as scope:
                            scopes.append(scope)
                            returned.append(await client.call_tool("demo_context", {}))
                    finally:
                        finished.set()

                async with anyio.create_task_group() as tasks:
                    tasks.start_soon(first_request)
                    await entered.wait()
                    busy = await client.call_tool("demo_context", {})
                    self.assertTrue(busy.is_error)
                    self.assertEqual(
                        busy.structured_content["data"]["reason"], "demo_busy"
                    )
                    scopes[0].cancel()
                    await finished.wait()
                    self.assertEqual(returned, [])
                    # Faster than the original two-second gate timeout: this
                    # proves wire cancellation drained admission, not expiry.
                    with anyio.fail_after(0.75):
                        while True:
                            recovered = await client.call_tool("demo_context", {})
                            if not recovered.is_error:
                                break
                            self.assertEqual(
                                recovered.structured_content["data"]["reason"],
                                "demo_busy",
                            )
                            await anyio.sleep(0.01)
                    self.assertEqual(
                        recovered.structured_content["data"]["persona"], "analyst"
                    )

        async def bounded():
            with anyio.fail_after(10):
                for mode in ("2026-07-28", "legacy"):
                    await check_mode(mode)

        anyio.run(bounded)


if __name__ == "__main__":
    if sys.argv[1:] == ["--blocking-fixture"]:
        anyio.run(blocking_fixture)
    else:
        unittest.main()
