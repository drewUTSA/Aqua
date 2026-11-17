"""Canonical report context, unchanged numeric golds and real SDK response caps."""

from dataclasses import replace
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import anyio
from mcp import Client
from mcp_types import JSONRPCResponse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eval.banking.data import BankingDenied  # noqa: E402
from mcp_demo import data, guidance, protocol, reports  # noqa: E402
from tools.bank_demo.test_demo_sdk import parameters  # noqa: E402

# Pre-brief report row golds, captured before implementation. Adding context
# must not silently change any of the seventeen aggregate numeric contracts.
EXPECTED = {
    "deposit_portfolio_summary": (
        "deposit_help",
        "fee120dabdd0e96982968826e315f4abbf6ab30a3552c51713b01187d4b58fc9",
    ),
    "service_case_summary": (
        "service_help",
        "54050fa9063e742e623188c6abf1c0c450c076e5621bf293c2423abcad365f0a",
    ),
    "consumer_pipeline_summary": (
        "consumer_help",
        "e71cc406f4f9082e1553c719a7090c91bfd373958710de1f52a038f3eb73680b",
    ),
    "commercial_exposure_summary": (
        "commercial_help",
        "b8aa39aaf6268c81bbb4025b8b4fbc3f2cb24b61637f20301cf9d1115cc9078d",
    ),
    "credit_review_summary": (
        "credit_help",
        "6728703309d01c6120a295912dbafb2bfeb4039258026626b0e6db25119e5301",
    ),
    "servicing_exception_summary": (
        "servicing_help",
        "68afa07c193c3251ce427f848f94070add445c35dcef33066fb56c7eb6eae52b",
    ),
    "payment_exception_summary": (
        "payment_help",
        "730c1aefd1b7f0f16a4a2ad8d9c698067b4480ccf9fd928e2dd9ec8d49abbef9",
    ),
    "liquidity_assumption_summary": (
        "treasury_help",
        "86879f0767a21e452eda10eaee9b87250b7aaae5134d0f209934f7d4ee4e1312",
    ),
    "reconciliation_summary": (
        "finance_help",
        "5c92a0af5a37179e0b6a68942de50d9b0bc0c21e304e4daf840b6a7555f97eff",
    ),
    "fraud_workload_summary": (
        "fraud_help",
        "6a643362627ddb898c5c9b7b3e53746e079be876d3eb81c8aab47b1648726461",
    ),
    "program_control_inventory": (
        "program_help",
        "be0ed120e271acb6263625a2da61bf1cd331b2d597386285aa5d3e5b45da5377",
    ),
    "policy_obligation_inventory": (
        "policy_help",
        "66a96a313b083b202a20449a8ff6468f6a7cebffcff9f849ffb37907a609c9b2",
    ),
    "fiduciary_workload_summary": (
        "trust_help",
        "7ce4c4036038e10de850b82a6cedcda30630b1963708a78cbe0ade1d4029ecb2",
    ),
    "service_health_summary": (
        "operations_help",
        "06cf406e912eda031a00b3f61fa2f3cbe711d2764fa4cc55fd2e5e6b7ed17975",
    ),
    "training_completion_summary": (
        "people_help",
        "dcb9101e4ca9058d776c5d314555fea600e6bc8c667adc753c6f86b515ac1237",
    ),
    "vendor_review_summary": (
        "vendor_help",
        "38825301263bf0547b0e46b78deb592bf6d5d36d0ec7eab6363cace8d7e27ec4",
    ),
    "audit_issue_summary": (
        "audit_help",
        "9ccad8a49eceaef87e7494b318935b0869cbbed53dd57d3ff6d348f9ff898701",
    ),
}
DENIALS = (protocol.DemoDenied, BankingDenied)


def procedure(actor, report_id, **changes):
    values = {
        "source_revision": data.SOURCE_REVISION,
        "guidance_revision": guidance.GUIDANCE_REVISION,
        "as_of": data.AS_OF,
    }
    return guidance.procedure_for_report(actor, report_id, **(values | changes))


class ReportBriefTests(unittest.TestCase):
    def test_all_seventeen_reports_bind_one_canonical_cited_procedure_and_snapshot(
        self,
    ):
        actor = protocol.actor_for("manager")
        self.assertEqual(set(EXPECTED), set(reports.REPORTS))
        for report_id, (source_id, _) in EXPECTED.items():
            with self.subTest(report=report_id):
                report = reports.run_report(actor, report_id)
                brief = report["companion_brief"]
                self.assertEqual(brief["report_id"], report_id)
                self.assertEqual(brief["department"], report["department"])
                for name in (
                    "source_revision",
                    "source_version",
                    "as_of",
                    "period",
                    "period_start",
                    "period_end",
                    "period_complete",
                    "currency",
                    "metric_definition",
                ):
                    self.assertEqual(brief[name], report[name])
                self.assertEqual(brief["guidance_revision"], guidance.GUIDANCE_REVISION)
                self.assertEqual(brief["procedure"]["citation"]["source_id"], source_id)
                self.assertTrue(brief["procedure"]["fictional_policy"])
                self.assertFalse(brief["procedure"]["public_education"])
                self.assertEqual(brief["procedure"], procedure(actor, report_id))
                self.assertEqual(
                    brief["freshness_basis"],
                    "fixed_demo_snapshot_not_live_bank_data_or_policy",
                )
                self.assertFalse(brief["period_complete"])

    def test_all_seventeen_preexisting_row_golds_are_unchanged(self):
        actor = protocol.actor_for("manager")
        for report_id, (_, expected_sha) in EXPECTED.items():
            with self.subTest(report=report_id):
                report = reports.run_report(actor, report_id)
                self.assertEqual(
                    hashlib.sha256(protocol.canonical(report["rows"])).hexdigest(),
                    expected_sha,
                )

    def test_procedure_scope_and_forged_authority_deny_before_projection(self):
        manager = protocol.actor_for("manager")
        for persona in ("none", "teller", "analyst"):
            actor = protocol.actor_for(persona)
            for report_id in EXPECTED:
                if report_id not in actor.scope.report_ids:
                    with (
                        self.subTest(persona=persona, report=report_id),
                        patch.object(guidance, "_project") as project,
                    ):
                        with self.assertRaises(DENIALS):
                            procedure(actor, report_id)
                        project.assert_not_called()
        for changed in (
            {"tenant_id": "99999999-9999-4999-8999-999999999999"},
            {"principal_id": protocol.actor_for("teller").scope.principal_id},
            {"authorization_revision": "0" * 64},
            {"object_ids": manager.scope.object_ids - {"third_party_risk"}},
            {"report_ids": manager.scope.report_ids - {"vendor_review_summary"}},
            {"tool_ids": manager.scope.tool_ids - {"bank_policy"}},
            {"tool_ids": manager.scope.tool_ids - {"read_report"}},
        ):
            actor = replace(manager, scope=replace(manager.scope, **changed))
            with (
                self.subTest(field=list(changed)),
                patch.object(guidance, "_project") as project,
            ):
                with self.assertRaises(DENIALS):
                    procedure(actor, "vendor_review_summary")
                project.assert_not_called()

    def test_stale_source_guidance_date_and_arbitrary_identifiers_deny(self):
        actor = protocol.actor_for("manager")
        for changes in (
            {"source_revision": "0" * 64},
            {"guidance_revision": "f" * 64},
            {"as_of": "2026-11-17"},
            {"source_revision": True},
            {"guidance_revision": data.SOURCE_REVISION},
            {"as_of": data.AS_OF + "\n"},
        ):
            with (
                self.subTest(field=list(changes)),
                patch.object(guidance, "_project") as project,
            ):
                with self.assertRaises(DENIALS):
                    procedure(actor, "reconciliation_summary", **changes)
                project.assert_not_called()
        for identifier in (
            True,
            [],
            "SELECT * FROM records",
            "vendor_review_summary\u200b",
            "https://outside.invalid",
        ):
            with (
                self.subTest(type=type(identifier).__name__),
                self.assertRaises(DENIALS),
            ):
                procedure(actor, identifier)

    def test_brief_suggestions_are_bounded_inert_data_without_executable_parameters(
        self,
    ):
        actor = protocol.actor_for("manager")
        for report_id in EXPECTED:
            brief = reports.run_report(actor, report_id)["companion_brief"]
            self.assertLessEqual(len(protocol.canonical(brief)), 8192)
            self.assertEqual(len(brief["caveats"]), 3)
            self.assertEqual(len(brief["next_steps"]), 3)
            self.assertTrue(brief["data_only"] and brief["synthetic"])
            self.assertEqual(brief["model_calls"], 0)
            self.assertFalse(
                brief["instruction_authority"]
                or brief["approval_recorded"]
                or brief["execution_enabled"]
                or brief["bank_authentication"]
            )
            for suggestion in brief["next_steps"]:
                self.assertLessEqual(len(suggestion["text"]), 300)
                self.assertFalse(suggestion["execution_enabled"])
                self.assertFalse(
                    {
                        "tool",
                        "tool_name",
                        "arguments",
                        "sql",
                        "url",
                        "command",
                        "approved",
                    }
                    & suggestion.keys()
                )
            self.assertTrue(brief["next_steps"][-1]["requires_explicit_user_request"])

    def test_mutating_a_returned_brief_does_not_change_the_next_report_or_sources(self):
        actor = protocol.actor_for("manager")
        first = reports.run_report(actor, "vendor_review_summary")["companion_brief"]
        original = protocol.canonical(first)
        first["procedure"]["text"] = "Foreign instructions must not persist"
        first["procedure"]["citation"]["source_id"] = "foreign"
        first["next_steps"][0]["execution_enabled"] = True
        second = reports.run_report(actor, "vendor_review_summary")["companion_brief"]
        self.assertEqual(protocol.canonical(second), original)
        self.assertEqual(second["guidance_revision"], guidance.GUIDANCE_REVISION)

    def test_every_report_brief_crosses_real_modern_and_legacy_stdio_with_frame_caps(
        self,
    ):
        async def check():
            with anyio.fail_after(10):
                for mode in ("2026-07-28", "legacy"):
                    async with Client(parameters("manager"), mode=mode) as client:
                        for report_id, (source_id, expected_sha) in EXPECTED.items():
                            reply = await client.call_tool(
                                "run_demo_report", {"report_id": report_id}
                            )
                            self.assertFalse(reply.is_error)
                            result = reply.structured_content["data"]
                            self.assertEqual(
                                result["companion_brief"]["procedure"]["citation"][
                                    "source_id"
                                ],
                                source_id,
                            )
                            self.assertEqual(
                                hashlib.sha256(
                                    protocol.canonical(result["rows"])
                                ).hexdigest(),
                                expected_sha,
                            )
                            wire = JSONRPCResponse(
                                jsonrpc="2.0",
                                id=100,
                                result=reply.model_dump(
                                    by_alias=True, exclude_none=True
                                ),
                            )
                            self.assertLessEqual(
                                len(
                                    wire.model_dump_json(
                                        by_alias=True, exclude_none=True
                                    ).encode()
                                )
                                + 1,
                                protocol.MAX_FRAME_BYTES,
                            )

        anyio.run(check)


if __name__ == "__main__":
    unittest.main()
