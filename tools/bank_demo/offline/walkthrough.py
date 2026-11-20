"""Run a fictional employee walkthrough through the official local MCP client."""

import argparse
import json
import os
from pathlib import Path
import sys

import anyio
from mcp import Client
from mcp.client.stdio import StdioServerParameters


async def walkthrough(role):
    root = Path(__file__).resolve().parent
    variables = {
        k: v
        for k, v in os.environ.items()
        if k.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP"}
    }
    server = StdioServerParameters(
        command=sys.executable,
        args=["-B", "-I", str(root / "serve_demo.py"), "--persona", role],
        env=variables,
    )
    async with Client(server, mode="2026-07-28", read_timeout_seconds=10) as client:

        async def call(name, **args):
            result = await client.call_tool(name, args)
            body = result.structured_content
            if (
                result.is_error
                or not body["synthetic"]
                or body["execution_enabled"]
                or body["approval_recorded"]
            ):
                raise RuntimeError(f"Unexpected demo result for {name}")
            return body["data"]

        context = await call("demo_context")
        if context["persona"] != role:
            raise RuntimeError("Unexpected demo persona")
        if role == "teller":
            report = await call("run_demo_report", report_id="service_case_summary")
            guide = await call(
                "search_demo_guidance",
                query="How should our fictional team follow up on a complaint?",
                limit=1,
            )
            source = report["companion_brief"]["procedure"]
            if guide["results"] != [source]:
                raise RuntimeError(
                    "The teller procedure did not match the report citation"
                )
            return {
                "persona": role,
                "periodEnd": report["period_end"],
                "openOrInReview": sum(
                    r["case_count"] for r in report["rows"] if r["status"] != "closed"
                ),
                "overdue": sum(r["overdue_open_count"] for r in report["rows"]),
                "procedure": source["citation"]["source_id"],
            }
        if role == "manager":
            payments = await call(
                "run_demo_report", report_id="payment_exception_summary"
            )
            services = await call("run_demo_report", report_id="service_health_summary")
            wire = next(r for r in payments["rows"] if r["rail"] == "wire")
            degraded = next(r for r in services["rows"] if r["status"] == "degraded")
            return {
                "persona": role,
                "periodEnd": payments["period_end"],
                "heldWireUSD": wire["held_amount_usd"],
                "activeDegradedServiceIncidents": degraded["active_incident_count"],
                "executionEnabled": False,
            }
        report = await call("run_demo_report", report_id="reconciliation_summary")
        row = next(r for r in report["rows"] if r["branch"] == "central")
        trend = await call("analyze_monthly_trend", metric_id="gl_operating_surplus")
        proposal = await call(
            "prepare_review_proposal",
            report_id="reconciliation_summary",
            expected_source_revision=report["source_revision"],
            action_id="draft_internal_followup",
            note="Review the fictional Central statement and ledger difference.",
        )
        draft = proposal["proposal"]
        if (
            context["persona"] != "analyst"
            or proposal["status"] != "proposal_only"
            or draft["requires_human_approval"] is not True
            or draft["execution_enabled"] is not False
            or draft["approval_recorded"] is not False
            or draft["payload"]["artifact_id"] != report["artifact_id"]
        ):
            raise RuntimeError("The local report or proposal has unexpected scope")
        return {
            "persona": context["persona"],
            "periodEnd": report["period_end"],
            "centralDifferenceUSD": row["difference_usd"],
            "completeHistoricalMonths": trend["historical_fit"]["observed_points"],
            "evaluationFolds": trend["chronological_evaluation"]["evaluated_folds"],
            "excludedPartialPeriods": trend["excluded_partial_periods"],
            "proposalStatus": proposal["status"],
            "requiresHumanApproval": draft["requires_human_approval"],
            "executionEnabled": draft["execution_enabled"],
        }


async def main(role):
    with anyio.fail_after(40):
        print(json.dumps(await walkthrough(role), indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--role", choices=("analyst", "teller", "manager"), default="analyst"
    )
    anyio.run(main, parser.parse_args().role)
