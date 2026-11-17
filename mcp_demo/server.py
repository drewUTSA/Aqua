"""Official SDK stdio transport around bounded, fictional bank-demo tools."""

import json
import logging
import math
import sys
import time
from typing import Any, Literal

import anyio
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import MCPError
from mcp_types import (
    PROTOCOL_VERSION_META_KEY,
    CallToolResult,
    ListToolsResult,
    TextContent,
    Tool,
    ToolAnnotations,
)
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS, MODERN_PROTOCOL_VERSIONS
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from eval.banking import BankingDenied, create_proposal
from eval.banking.catalog import ACTION_IDS, REPORTS
from eval.banking.data import encode as banking_encode
from mcp_demo import data, finance, guidance, reports
from mcp_demo.finance_schema import with_finance_schema
from mcp_demo.protocol import (
    HANDLER_SECONDS,
    MAX_FRAME_BYTES,
    MAX_RESULT_BYTES,
    DemoDenied,
    actor_for,
    canonical,
    envelope,
    require,
    require_actor,
    require_tool,
)


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class NoArguments(Arguments):
    pass


ReportId = Literal[tuple(sorted(REPORTS))]
ActionId = Literal[tuple(sorted(ACTION_IDS))]


class ReportArguments(Arguments):
    report_id: ReportId
    period: Literal["2026-11"] = "2026-11"
    currency: Literal["USD"] = "USD"


class GuidanceArguments(Arguments):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=3, ge=1, le=3)


class FinanceArguments(Arguments):
    model_config = ConfigDict(
        **{**Arguments.model_config, "json_schema_extra": with_finance_schema}
    )

    operation: Literal[
        "simple_interest",
        "amortizing_loan_payment",
        "percent_change",
        "liquidity_coverage",
        "reconciliation",
    ]
    # Keep numeric input types intact: the calculator rejects floats and bools.
    parameters: dict[str, Any] = Field(max_length=6)


class ProposalArguments(ReportArguments):
    expected_source_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    action_id: ActionId = "request_internal_review"
    note: str = Field(min_length=1, max_length=1024)


class TrendArguments(Arguments):
    metric_id: Literal[
        "gl_operating_income", "gl_operating_expense", "gl_operating_surplus"
    ] = "gl_operating_surplus"


ARGUMENTS = {
    "demo_context": NoArguments,
    "list_authorized_reports": NoArguments,
    "run_demo_report": ReportArguments,
    "search_demo_guidance": GuidanceArguments,
    "calculate_finance": FinanceArguments,
    "prepare_review_proposal": ProposalArguments,
    "analyze_monthly_trend": TrendArguments,
}
DESCRIPTIONS = {
    "demo_context": "Describe the fictional U.S./USD demonstration, fixed as-of date and server-selected persona. No real bank is connected.",
    "list_authorized_reports": "List only fictional aggregate reports in this process's current demo scope.",
    "run_demo_report": "Read one authorized, fictional November 2026 aggregate report. No SQL, customer records or live bank query.",
    "search_demo_guidance": "Find literal cited fictional policy or clearly separated public financial education. Does not establish a real bank's policy.",
    "calculate_finance": "Calculate a bounded deterministic financial example from plain numeric strings. USD only; not a quote, credit decision or action.",
    "prepare_review_proposal": "Prepare an unapproved, inert internal-review draft bound to this fictional report revision. Do not include real personal data. Cannot approve or execute.",
    "analyze_monthly_trend": "Fit and evaluate a descriptive trend on the server's authorized fictional monthly ledger. No caller rows, forecast or causality claim.",
}


def _result(payload, *, error=False):
    body = envelope(payload, source_revision=data.SOURCE_REVISION, as_of=data.AS_OF)
    # Text keeps legacy clients useful; structuredContent supports newer hosts.
    result = CallToolResult(
        content=[TextContent(type="text", text=canonical(body).decode("utf-8"))],
        structured_content=body,
        is_error=error,
    )
    require(
        len(result.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8"))
        <= MAX_RESULT_BYTES - 512,
        "demo_output_budget",
    )
    return result


def _error(category="demo_request_denied"):
    # The category is selected locally, never copied from a request/exception.
    return _result(
        {
            "status": "denied",
            "reason": category,
            "message": "I can help with the fictional examples available to this demo persona. Check the listed tools and their input fields.",
        },
        error=True,
    )


def _visible(actor):
    if actor.persona == "none":
        return {"demo_context"}
    names = set(ARGUMENTS)
    if "reconciliation_summary" not in actor.scope.report_ids:
        names.remove("analyze_monthly_trend")
    return names


def _dispatch(actor, name, values):
    if name == "demo_context":
        return {
            "status": "context",
            "name": "Aqua fictional bank demo",
            "persona": actor.persona,
            "tenant_id": actor.scope.tenant_id,
            "scope_source": "fixed_fictional_demo_registry_not_bank_identity",
            "authorized_report_ids": sorted(actor.scope.report_ids),
            "tools": sorted(_visible(actor)),
            "limits": {
                "handler_seconds": HANDLER_SECONDS,
                "message_bytes": MAX_FRAME_BYTES,
            },
            "notice": "All bank figures and procedures are fictional. No bank account is connected; this process cannot approve or execute actions.",
        }
    require(name in _visible(actor), "demo_scope_denied")
    if name == "list_authorized_reports":
        return {"status": "listed", "reports": reports.authorized_reports(actor)}
    if name == "run_demo_report":
        return reports.run_report(actor, **values)
    if name == "search_demo_guidance":
        return guidance.search(actor, **values)
    if name == "calculate_finance":
        require_tool(actor, "public_education")
        require("public_finance" in actor.scope.object_ids, "demo_scope_denied")
        return finance.calculate_finance(**values)
    if name == "analyze_monthly_trend":
        from mcp_demo.trends import analyze_monthly_trend

        return analyze_monthly_trend(actor, **values)
    require(name == "prepare_review_proposal", "demo_request_denied")
    require_tool(actor, "prepare_proposal")
    require(
        values["expected_source_revision"] == data.SOURCE_REVISION,
        "demo_source_changed",
    )
    now = int(time.time())
    artifact = reports.artifact_for(
        actor,
        values["report_id"],
        now,
        period=values["period"],
        currency=values["currency"],
    )
    payload = {
        "schemaVersion": 1,
        "action_id": values["action_id"],
        "report_id": values["report_id"],
        "artifact_id": artifact.artifact_id,
        "object_id": artifact.object_id,
        "note": values["note"],
    }
    proposal = create_proposal(
        banking_encode(payload),
        scope=actor.scope,
        artifact=artifact,
        now=now,
        expires_at=min(now + 300, artifact.expires_at),
    )
    return {
        "status": "proposal_only",
        "proposal_sha256": proposal.sha256,
        "proposal": json.loads(proposal.data),
        "message": "Here is the exact fictional review draft. It is unapproved and cannot execute; a real approval workflow is outside this demo.",
    }


def build_server(actor=None):
    """Construct SDK handlers; persona never comes from a tool argument."""
    actor = require_actor(actor_for() if actor is None else actor)
    semaphore = anyio.Semaphore(1)

    async def list_tools(context, params):
        return ListToolsResult(
            tools=[
                Tool(
                    name=name,
                    description=DESCRIPTIONS[name],
                    input_schema=ARGUMENTS[name].model_json_schema(),
                    annotations=ToolAnnotations(
                        read_only_hint=True,
                        destructive_hint=False,
                        idempotent_hint=name != "prepare_review_proposal",
                        open_world_hint=False,
                    ),
                )
                for name in sorted(_visible(actor))
            ]
        )

    async def call_tool(context, params):
        try:
            require(params.name in _visible(actor), "demo_scope_denied")
            raw = {} if params.arguments is None else params.arguments
            require(
                type(raw) is dict and len(canonical(raw)) <= 8192, "demo_input_budget"
            )
            values = ARGUMENTS[params.name].model_validate(raw).model_dump()
            return _result(_dispatch(actor, params.name, values))
        except (
            BankingDenied,
            DemoDenied,
            ValidationError,
            ValueError,
            KeyError,
            TypeError,
        ):
            return _error()

    async def boundary(context, call_next):
        if context.method != "tools/call":
            try:
                return await call_next(context)
            except Exception:
                raise MCPError(code=-32602, message="demo_request_denied") from None
        acquired = False
        try:
            semaphore.acquire_nowait()
            acquired = True
            started = time.monotonic()
            with anyio.fail_after(HANDLER_SECONDS):
                result = await call_next(context)
                # Synchronous bounded calculations cannot be preempted by an
                # async cancel scope; never publish a result that finished late.
                if time.monotonic() - started > HANDLER_SECONDS:
                    return _error("demo_deadline")
                return result
        except anyio.WouldBlock:
            return _error("demo_busy")
        except TimeoutError:
            return _error("demo_deadline")
        except Exception:
            return _error()
        finally:
            if acquired:
                semaphore.release()

    server = Server(
        "aqua-fictional-bank-demo",
        version="1.0.0",
        instructions="Fictional U.S./USD sales demonstration only. Use current server scope, cited data and exact calculations. Never claim a real bank connection, approval, payment, compliance certification or model training.",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )
    server.middleware.append(boundary)
    return server


class BoundedInput:
    """Byte bound only; the SDK parses and owns all MCP/JSON-RPC messages."""

    def __init__(self, stream):
        self.stream = stream

    def __aiter__(self):
        return self

    async def __anext__(self):
        raw = await anyio.to_thread.run_sync(self.stream.readline, MAX_FRAME_BYTES + 1)
        if not raw:
            raise StopAsyncIteration
        require(
            len(raw) <= MAX_FRAME_BYTES and raw.endswith(b"\n"), "demo_frame_budget"
        )
        try:
            line = raw.decode("utf-8")
            validate_frame_safety(line)
            return line
        except UnicodeError:
            raise DemoDenied("demo_frame_invalid") from None


def validate_frame_safety(line):
    """Reject ambiguous/unbounded JSON; the SDK still parses and dispatches it."""

    def unique(items):
        result = {}
        for name, value in items:
            require(name not in result, "demo_frame_invalid")
            result[name] = value
        return result

    def number(value, convert):
        require(len(value) <= 64, "demo_frame_budget")
        result = convert(value)
        require(
            not isinstance(result, float) or math.isfinite(result), "demo_frame_invalid"
        )
        return result

    def constant(_):
        raise DemoDenied("demo_frame_invalid")

    try:
        value = json.loads(
            line,
            object_pairs_hook=unique,
            parse_int=lambda value: number(value, int),
            parse_float=lambda value: number(value, float),
            parse_constant=constant,
        )
    except (ValueError, RecursionError):
        raise DemoDenied("demo_frame_invalid") from None
    pending, nodes = [(value, 0)], 0
    while pending:
        current, depth = pending.pop()
        nodes += 1
        require(nodes <= 4096, "demo_frame_budget")
        if isinstance(current, (dict, list)):
            require(depth < 32, "demo_frame_budget")
            children = current.values() if isinstance(current, dict) else current
            pending.extend((child, depth + 1) for child in children)

    # SDK negotiation happens before server middleware and may return an
    # unsupported revision verbatim. Only fixed known revisions reach it.
    if isinstance(value, dict) and isinstance(value.get("params"), dict):
        params = value["params"]
        if value.get("method") == "initialize" and "protocolVersion" in params:
            require(
                type(params["protocolVersion"]) is str
                and params["protocolVersion"]
                in (*HANDSHAKE_PROTOCOL_VERSIONS, *MODERN_PROTOCOL_VERSIONS),
                "demo_negotiation_denied",
            )
        meta = params.get("_meta")
        if isinstance(meta, dict) and PROTOCOL_VERSION_META_KEY in meta:
            require(
                type(meta[PROTOCOL_VERSION_META_KEY]) is str
                and meta[PROTOCOL_VERSION_META_KEY] in MODERN_PROTOCOL_VERSIONS,
                "demo_negotiation_denied",
            )


class BoundedOutput:
    def __init__(self, stream):
        self.stream = stream

    async def write(self, value):
        raw = value.encode("utf-8")
        require(len(raw) <= MAX_RESULT_BYTES, "demo_frame_budget")
        await anyio.to_thread.run_sync(self.stream.write, raw)

    async def flush(self):
        await anyio.to_thread.run_sync(self.stream.flush)


class SafeReceive:
    """Remove SDK parse-error inputs before its dispatcher formats an error."""

    def __init__(self, stream):
        self.stream = stream

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await self.receive()
        except anyio.EndOfStream:
            raise StopAsyncIteration

    async def receive(self):
        item = await self.stream.receive()
        return ValueError("demo_invalid_frame") if isinstance(item, Exception) else item

    def receive_nowait(self):
        item = self.stream.receive_nowait()
        return ValueError("demo_invalid_frame") if isinstance(item, Exception) else item

    def clone(self):
        return SafeReceive(self.stream.clone())

    async def __aenter__(self):
        await self.stream.__aenter__()
        return self

    async def __aexit__(self, *arguments):
        return await self.stream.__aexit__(*arguments)


async def run_stdio(actor):
    # No SDK diagnostic can retain a prompt, tool argument or returned data.
    logging.disable(logging.CRITICAL)
    server = build_server(actor)
    async with stdio_server(
        stdin=BoundedInput(sys.stdin.buffer), stdout=BoundedOutput(sys.stdout.buffer)
    ) as streams:
        await server.run(
            SafeReceive(streams[0]), streams[1], server.create_initialization_options()
        )
