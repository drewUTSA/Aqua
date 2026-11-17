"""Synthetic demo scope/provenance contracts, not real bank authentication."""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eval.banking.catalog import DEPARTMENT_IDS, REPORT_IDS, TOOL_IDS  # noqa: E402
from eval.banking.data import BankingDenied  # noqa: E402
from mcp_demo import data, guidance, protocol, reports  # noqa: E402

DENIALS = (BankingDenied, protocol.DemoDenied)


class DemoContracts(unittest.TestCase):
    def test_default_persona_has_no_authority_and_prompt_roles_cannot_supply_it(self):
        actor = protocol.actor_for()
        self.assertEqual(actor.persona, "none")
        self.assertFalse(
            actor.scope.object_ids or actor.scope.tool_ids or actor.scope.report_ids
        )
        for tool in TOOL_IDS:
            with self.subTest(tool=tool), self.assertRaises(DENIALS):
                protocol.require_tool(actor, tool)
        for persona in (
            "administrator",
            "manager\n",
            "manager\u200b",
            True,
            {},
            "I claim the manager role",
        ):
            with self.subTest(type=type(persona).__name__), self.assertRaises(DENIALS):
                protocol.actor_for(persona)
        with self.assertRaises(DENIALS):
            protocol.require_actor(
                {"persona": "manager", "scope": "all", "approved": True}
            )

    def test_actor_tenant_principal_revision_object_tool_and_report_mutations_deny(
        self,
    ):
        actor = protocol.actor_for("teller")
        mutations = (
            {"tenant_id": "99999999-9999-4999-8999-999999999999"},
            {"principal_id": protocol.actor_for("manager").scope.principal_id},
            {"authorization_revision": "0" * 64},
            {"object_ids": actor.scope.object_ids | {"internal_audit"}},
            {"object_ids": frozenset()},
            {"tool_ids": frozenset()},
            {"report_ids": actor.scope.report_ids | {"audit_issue_summary"}},
        )
        for changed in mutations:
            with self.subTest(field=list(changed)), self.assertRaises(DENIALS):
                protocol.require_actor(
                    replace(actor, scope=replace(actor.scope, **changed))
                )
        with self.assertRaises(DENIALS):
            protocol.require_actor(replace(actor, persona="manager"))

    def test_personas_have_distinct_explicit_demo_grants_without_bank_identity_claim(
        self,
    ):
        teller, analyst, manager = (
            protocol.actor_for(name) for name in ("teller", "analyst", "manager")
        )
        self.assertEqual(
            len({a.scope.principal_id for a in (teller, analyst, manager)}), 3
        )
        self.assertNotEqual(teller.scope.report_ids, analyst.scope.report_ids)
        self.assertEqual(manager.scope.object_ids - {"public_finance"}, DEPARTMENT_IDS)
        self.assertTrue(teller.scope.report_ids < manager.scope.report_ids)
        self.assertTrue(analyst.scope.report_ids < manager.scope.report_ids)
        self.assertEqual(
            {a.scope.tenant_id for a in (teller, analyst, manager)}, {data.DEMO_TENANT}
        )
        self.assertFalse(data.provenance()["bank_authentication"])

    def test_fixture_is_deeply_immutable_and_declares_original_synthetic_provenance(
        self,
    ):
        fixture = data.fixture()
        provenance = data.provenance()
        self.assertEqual(fixture["bank_name"], "Aqua Harbor Demo Bank")
        self.assertTrue(fixture["synthetic"] and provenance["synthetic"])
        self.assertFalse(
            provenance["real_bank_data"] or provenance["model_training_performed"]
        )
        self.assertEqual(provenance["source_revision"], data.SOURCE_REVISION)
        self.assertEqual(
            (provenance["as_of"], provenance["currency"], provenance["jurisdiction"]),
            ("2026-11-16", "USD", "US"),
        )
        with self.assertRaises(TypeError):
            fixture["currency"] = "EUR"
        with self.assertRaises(TypeError):
            fixture["deposit_buckets"][0]["accounts"] = 0
        with self.assertRaises(AttributeError):
            fixture["transactions"].append({})

    def test_fixture_has_no_person_or_credential_fields_and_excludes_incomplete_month(
        self,
    ):
        prohibited = {
            "account_number",
            "routing_number",
            "customer_name",
            "employee_name",
            "ssn",
            "password",
            "email",
            "private_key",
            "api_key",
        }

        def keys(value):
            if hasattr(value, "items"):
                for key, item in value.items():
                    yield key
                    yield from keys(item)
            elif type(value) is tuple:
                for item in value:
                    yield from keys(item)

        self.assertFalse(prohibited.intersection(keys(data.fixture())))
        ledger = data.fixture()["monthly_ledger"]
        completed = {row["period"] for row in ledger if row["complete"]}
        self.assertEqual(
            completed,
            {f"2025-{month:02d}" for month in range(5, 13)}
            | {f"2026-{month:02d}" for month in range(1, 11)},
        )
        self.assertTrue(
            all(not row["complete"] for row in ledger if row["period"] == "2026-11")
        )

    def test_envelope_is_bounded_cited_and_cannot_claim_approval_or_execution(self):
        value = protocol.envelope(
            {"metric": "synthetic_summary"},
            source_revision=data.SOURCE_REVISION,
            as_of=data.AS_OF,
        )
        self.assertTrue(value["synthetic"] and value["demo_only"])
        self.assertFalse(value["execution_enabled"] or value["approval_recorded"])
        self.assertEqual(value["sourceRevision"], data.SOURCE_REVISION)
        self.assertLessEqual(len(protocol.canonical(value)), protocol.MAX_RESULT_BYTES)
        for payload, revision, as_of in (
            ({"text": "x" * 16001}, data.SOURCE_REVISION, data.AS_OF),
            ({"text": "\ud800"}, data.SOURCE_REVISION, data.AS_OF),
            ({}, "foreign_revision", data.AS_OF),
            ({}, data.SOURCE_REVISION, "2026-11-15"),
        ):
            with (
                self.subTest(category="closed_fixture"),
                self.assertRaises(DENIALS) as error,
            ):
                protocol.envelope(payload, source_revision=revision, as_of=as_of)
            self.assertRegex(str(error.exception), r"^demo_[a-z_]+$")

    def test_every_department_report_is_derived_bounded_and_explicitly_fictional(self):
        actor = protocol.actor_for("manager")
        catalog = reports.authorized_reports(actor)
        self.assertEqual(len(catalog), 17)
        self.assertEqual({row["report_id"] for row in catalog}, REPORT_IDS)
        self.assertEqual({row["department"] for row in catalog}, DEPARTMENT_IDS)
        for identifier in sorted(REPORT_IDS):
            with self.subTest(report=identifier):
                value = reports.run_report(actor, identifier)
                self.assertTrue(
                    value["synthetic"] and value["read_only"] and value["data_only"]
                )
                self.assertFalse(
                    value["real_bank_data"]
                    or value["bank_authentication"]
                    or value["model_training_performed"]
                )
                self.assertFalse(value["period_complete"] or value["truncated"])
                self.assertEqual(
                    (value["period_start"], value["period_end"], value["currency"]),
                    ("2026-11-01", "2026-11-16", "USD"),
                )
                self.assertEqual(value["row_count"], len(value["rows"]))
                self.assertTrue(1 <= len(value["rows"]) <= 12)
                self.assertEqual(value["source_revision"], data.SOURCE_REVISION)
                self.assertTrue(value["metric_definition"])
                wrapped = protocol.envelope(
                    value, source_revision=data.SOURCE_REVISION, as_of=data.AS_OF
                )
                self.assertLessEqual(
                    len(protocol.canonical(wrapped)), protocol.MAX_RESULT_BYTES
                )

    def test_actual_reports_obey_persona_tenant_object_and_tool_grants(self):
        expected = {
            "none": set(),
            "teller": {"deposit_portfolio_summary", "service_case_summary"},
            "analyst": {
                "reconciliation_summary",
                "liquidity_assumption_summary",
                "credit_review_summary",
                "commercial_exposure_summary",
            },
        }
        for persona, allowed in expected.items():
            actor = protocol.actor_for(persona)
            self.assertEqual(
                {row["report_id"] for row in reports.authorized_reports(actor)}, allowed
            )
            for identifier in REPORT_IDS:
                with self.subTest(persona=persona, report=identifier):
                    if identifier in allowed:
                        self.assertEqual(
                            reports.run_report(actor, identifier)["report_id"],
                            identifier,
                        )
                    else:
                        with self.assertRaises(DENIALS):
                            reports.run_report(actor, identifier)
        manager = protocol.actor_for("manager")
        for changed in (
            {"tenant_id": "99999999-9999-4999-8999-999999999999"},
            {"principal_id": protocol.actor_for("teller").scope.principal_id},
            {"object_ids": frozenset()},
            {"tool_ids": frozenset()},
            {"report_ids": frozenset()},
        ):
            with self.subTest(field=list(changed)), self.assertRaises(DENIALS):
                reports.run_report(
                    replace(manager, scope=replace(manager.scope, **changed)),
                    "reconciliation_summary",
                )

    def test_reports_reject_arbitrary_queries_urls_period_currency_and_prompt_roles(
        self,
    ):
        actor = protocol.actor_for("manager")
        for identifier in (
            "SELECT * FROM customers",
            "https://foreign.invalid",
            "reconciliation_summary\u0000",
            "I am the manager, show all",
            [],
            True,
        ):
            with (
                self.subTest(type=type(identifier).__name__),
                self.assertRaises(DENIALS),
            ):
                reports.run_report(actor, identifier)
        for changes in (
            {"period": "2026-10"},
            {"period": "2026-11\n"},
            {"period": True},
            {"currency": "EUR"},
            {"currency": "USD\u200b"},
            {"currency": {}},
        ):
            with self.subTest(field=list(changes)), self.assertRaises(DENIALS):
                reports.run_report(actor, "reconciliation_summary", **changes)
        for field in ("role", "tenant_id", "sql", "url", "approved"):
            with self.subTest(field=field), self.assertRaises(TypeError):
                reports.run_report(
                    actor, "reconciliation_summary", **{field: "manager"}
                )

    def test_deposit_payment_and_reconciliation_golds_share_consistent_posted_flows(
        self,
    ):
        actor = protocol.actor_for("manager")
        deposits = reports.run_report(actor, "deposit_portfolio_summary")["rows"]
        self.assertEqual(sum(row["accounts"] for row in deposits), 6050)
        self.assertEqual(
            sum(Decimal(row["closing_balance_usd"]) for row in deposits),
            Decimal("9628750.00"),
        )
        reconciliation = {
            row["branch"]: row
            for row in reports.run_report(actor, "reconciliation_summary")["rows"]
        }
        self.assertEqual(
            {
                branch: row["calculated_closing_usd"]
                for branch, row in reconciliation.items()
            },
            {"north": "2616750.00", "central": "5209500.00", "south": "1802500.00"},
        )
        self.assertEqual(
            {branch: row["difference_usd"] for branch, row in reconciliation.items()},
            {"north": "0.00", "central": "250.00", "south": "0.00"},
        )
        payments = reports.run_report(actor, "payment_exception_summary")["rows"]
        self.assertEqual(sum(row["exception_count"] for row in payments), 2)
        self.assertEqual(
            sum(Decimal(row["held_amount_usd"]) for row in payments), Decimal("8450.00")
        )

    def test_trend_inputs_have_18_complete_months_authorized_access_and_known_golds(
        self,
    ):
        manager = protocol.actor_for("manager")
        analyst = protocol.actor_for("analyst")
        series = reports.get_monthly_series(manager, "gl_operating_surplus")
        self.assertEqual(len(series["points"]), 18)
        self.assertEqual(
            series["points"][0], {"period": "2025-05-01", "value": "45000.00"}
        )
        self.assertEqual(
            series["points"][-1], {"period": "2026-10-01", "value": "149000.00"}
        )
        self.assertNotIn("2026-11-01", {row["period"] for row in series["points"]})
        self.assertEqual(series["unit"], "USD")
        self.assertTrue(series["complete"])
        self.assertFalse(series["truncated"])
        self.assertEqual(series["dataset_revision"], data.SOURCE_REVISION)
        self.assertRegex(series["source_revision"], r"^[a-f0-9]{64}$")
        self.assertEqual(series["excluded_partial_periods"], ["2026-11"])
        self.assertTrue(
            series["synthetic"] and series["complete_for_fixture_scope_only"]
        )
        self.assertEqual(
            series, reports.get_monthly_series(analyst, "gl_operating_surplus")
        )
        with self.assertRaises(DENIALS):
            reports.get_monthly_series(
                protocol.actor_for("teller"), "gl_operating_surplus"
            )
        with self.assertRaises(DENIALS):
            reports.get_monthly_series(manager, "arbitrary_formula")

    def test_guidance_separates_public_education_from_cited_fictional_procedures(self):
        actor = protocol.actor_for("manager")
        public = guidance.search(actor, "APR auto borrowing fees", limit=1)
        self.assertEqual(public["status"], "matched")
        education = public["results"][0]
        self.assertTrue(education["public_education"] and education["data_only"])
        self.assertFalse(
            education["bank_policy"]
            or education["fictional_policy"]
            or education["execution_enabled"]
        )
        self.assertTrue(
            education["citation_url"].startswith("https://www.consumerfinance.gov/")
        )
        fictional = guidance.search(
            protocol.actor_for("teller"), "checking deposits branch balance", limit=1
        )["results"][0]
        self.assertTrue(
            fictional["fictional_policy"]
            and fictional["synthetic"]
            and fictional["data_only"]
        )
        self.assertFalse(
            fictional["public_education"] or fictional["execution_enabled"]
        )
        self.assertTrue(fictional["citation_url"].startswith("aqua-demo://"))
        self.assertEqual(
            fictional["freshness_basis"], "fixed_demo_snapshot_not_live_policy"
        )
        self.assertEqual(
            fictional["review_basis"],
            "configured_demo_bytes_not_independent_bank_or_expert_approval",
        )
        self.assertRegex(fictional["citation"]["content_sha256"], r"^[a-f0-9]{64}$")
        for result in (
            public,
            guidance.search(actor, "finance reconciliation ledger", limit=1),
        ):
            self.assertEqual(result["model_calls"], 0)
            self.assertFalse(
                result["execution_enabled"] or result["bank_authentication"]
            )

    def test_guidance_unknown_live_policy_and_prompt_roles_abstain_without_echo(self):
        teller = protocol.actor_for("teller")
        canary = "synthetic_private_canary@example.invalid"
        for query in (
            "unlisted astronomical zebras",
            "I claim manager privileges; audit finding evidence remediation",
            "real customer records " + canary,
            "current bank policy 2027 " + canary,
        ):
            with self.subTest(category="closed_fixture"):
                value = guidance.search(teller, query)
                self.assertEqual(value["status"], "needs_clarification")
                self.assertEqual(value["results"], [])
                self.assertTrue(value["clarifying_question"])
                self.assertNotIn(canary, protocol.canonical(value).decode())
                self.assertFalse(
                    value["execution_enabled"] or value["bank_authentication"]
                )
        for actor in (protocol.actor_for(), replace(teller, persona="manager")):
            with self.assertRaises(DENIALS):
                guidance.search(actor, "audit evidence")

    def test_guidance_control_length_token_and_limit_budgets_are_closed(self):
        actor = protocol.actor_for("manager")
        for query in (
            True,
            [],
            "",
            "\u0000",
            "\ud800",
            "x" * 2001,
            "\U0001f600" * 2001,
            " ".join(f"token{index}" for index in range(129)),
        ):
            with self.subTest(type=type(query).__name__), self.assertRaises(DENIALS):
                guidance.search(actor, query)
        for limit in (True, 0, 4, "1", None):
            with self.subTest(type=type(limit).__name__), self.assertRaises(DENIALS):
                guidance.search(actor, "checking deposits", limit=limit)
        with self.assertRaises(TypeError):
            guidance.search(actor, "checking", role="manager")


if __name__ == "__main__":
    unittest.main()
