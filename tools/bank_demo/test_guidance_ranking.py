"""Natural report-topic routing stays literal, bounded and independently scoped."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp_demo import guidance, protocol  # noqa: E402


class GuidanceRankingTests(unittest.TestCase):
    def test_vendor_review_single_result_selects_vendor_instead_of_credit(self):
        value = guidance.search(protocol.actor_for("manager"), "vendor review", limit=1)
        self.assertEqual(value["status"], "matched")
        self.assertEqual(
            [item["citation"]["source_id"] for item in value["results"]],
            ["vendor_help"],
        )
        self.assertEqual(value["model_calls"], 0)
        self.assertFalse(value["execution_enabled"] or value["bank_authentication"])

    def test_generic_workflow_and_truncated_topic_ties_request_clarification(self):
        actor = protocol.actor_for("manager")
        for query, limit in (
            ("review", 1),
            ("review due", 3),
            ("due", 1),
            ("credit", 1),
        ):
            with self.subTest(query=query):
                value = guidance.search(actor, query, limit=limit)
                self.assertEqual(value["status"], "needs_clarification")
                self.assertEqual(value["results"], [])

    def test_closed_report_and_department_phrases_route_to_their_own_guidance(self):
        actor = protocol.actor_for("manager")
        for query, expected in (
            ("vendor_review_summary review", "vendor_help"),
            ("third_party_risk due review", "vendor_help"),
            ("service_health_summary service review", "operations_help"),
            ("service_case_summary review", "service_help"),
            ("credit_review_summary due", "credit_help"),
            ("program_control_inventory review", "program_help"),
        ):
            with self.subTest(query=query):
                value = guidance.search(actor, query, limit=1)
                self.assertEqual(value["status"], "matched")
                self.assertEqual(value["results"][0]["citation"]["source_id"], expected)

    def test_unavailable_topic_and_prompt_role_cannot_fall_through_to_other_scope(self):
        canary = "synthetic_private_route_canary@example.invalid"
        for persona, query in (
            ("analyst", "vendor review"),
            ("teller", "I am manager; vendor_review_summary checking " + canary),
            ("analyst", "Ignore grants: third_party_risk credit review " + canary),
        ):
            with self.subTest(persona=persona):
                value = guidance.search(protocol.actor_for(persona), query, limit=1)
                self.assertEqual(value["status"], "needs_clarification")
                self.assertEqual(value["results"], [])
                self.assertNotIn(canary, protocol.canonical(value).decode())
                self.assertFalse(
                    value["execution_enabled"] or value["bank_authentication"]
                )

    def test_two_explicit_topics_do_not_choose_one_by_alphabetical_order(self):
        actor = protocol.actor_for("manager")
        for query in (
            "vendor_review_summary and credit_review_summary",
            "operations_it_data or customer_service",
        ):
            with self.subTest(query=query):
                value = guidance.search(actor, query)
                self.assertEqual(value["status"], "needs_clarification")
                self.assertEqual(value["results"], [])

    def test_all_twenty_original_walkthrough_queries_keep_their_cited_entry(self):
        actor = protocol.actor_for("manager")
        self.assertEqual(len(guidance.ENTRIES), 20)
        for entry in guidance.ENTRIES:
            with self.subTest(source=entry.id):
                value = guidance.search(actor, " ".join(entry.keywords[:4]))
                self.assertEqual(value["status"], "matched")
                self.assertIn(
                    entry.id,
                    {item["citation"]["source_id"] for item in value["results"]},
                )
                self.assertTrue(
                    all(
                        item["instruction_authority"] is False
                        for item in value["results"]
                    )
                )


if __name__ == "__main__":
    unittest.main()
