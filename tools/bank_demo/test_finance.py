"""Independent hand-worked golds and denial boundaries, without model calls."""

from decimal import localcontext
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eval.banking.data import encode  # noqa: E402
from mcp_demo.finance import FinanceDenied, calculate_finance  # noqa: E402


def loan(principal="100", rate="12", term="3"):
    return {
        "currency": "USD",
        "principal_usd": principal,
        "annual_rate_percent": rate,
        "term_months": term,
    }


class FinanceTests(unittest.TestCase):
    def result(self, operation, parameters):
        return calculate_finance(operation, parameters)["result"]

    def test_elapsed_days_use_the_stated_fixed_denominator(self):
        args = {
            "currency": "USD",
            "principal_usd": "3650",
            "annual_rate_percent": "10",
            "elapsed_days": "18",
        }
        for basis, interest, fraction in [
            ("Actual/360", "18.25", "18/360"),
            ("Actual/365 Fixed", "18.00", "18/365"),
        ]:
            with self.subTest(basis=basis):
                result = self.result(
                    "simple_interest_actual_days", {**args, "day_count_basis": basis}
                )
                self.assertEqual(result["interest_usd"], interest)
                self.assertEqual(result["year_fraction"], fraction)
                self.assertEqual(result["day_count_basis"], basis)
                self.assertEqual(result["elapsed_days"], "18")
                self.assertNotIn("term_months", result)

    def test_day_calculation_requires_its_own_term_and_basis(self):
        args = {
            "currency": "USD",
            "principal_usd": "18",
            "annual_rate_percent": "10",
            "elapsed_days": "1",
            "day_count_basis": "Actual/360",
        }
        self.assertEqual(
            self.result("simple_interest_actual_days", args)["interest_usd"], "0.01"
        )
        for bad in [
            {"term_months": "1"},
            {"day_count_basis": "Actual/Actual"},
            {"day_count_basis": "30/360"},
            {"elapsed_days": "0"},
            {"elapsed_days": "18301"},
            {"elapsed_days": "2.5"},
            {"elapsed_days": True},
        ]:
            with self.subTest(bad=bad), self.assertRaises(FinanceDenied):
                self.result("simple_interest_actual_days", {**args, **bad})
        with self.assertRaises(FinanceDenied):
            self.result(
                "simple_interest_actual_days",
                {k: v for k, v in args.items() if k != "day_count_basis"},
            )
        with self.assertRaises(FinanceDenied):
            self.result("simple_interest", args)

    def test_repeating_monthly_rate_pays_exact_half_cents_up(self):
        # In each one-month example the true interest is exactly half a cent.
        for principal, annual, payment in [
            ("24", "0.25", "24.01"),
            ("12", "0.5", "12.01"),
        ]:
            with self.subTest(annual=annual):
                result = self.result(
                    "amortizing_loan_payment", loan(principal, annual, "1")
                )
                for field in (
                    "scheduled_monthly_payment_usd",
                    "first_payment_usd",
                    "final_payment_usd",
                ):
                    self.assertEqual(result[field], payment)
                self.assertEqual(result["total_interest_usd"], "0.01")

    def test_long_schedule_preserves_each_half_cent(self):
        result = self.result("amortizing_loan_payment", loan("29170.01", "0.25", "360"))
        self.assertEqual(result["scheduled_monthly_payment_usd"], "84.11")
        self.assertEqual(result["final_payment_usd"], "85.16")
        self.assertEqual(result["total_interest_usd"], "1110.64")
        self.assertEqual(result["total_payments_usd"], "30280.65")

    def test_simple_interest_gold_and_exact_half_cent_rounding(self):
        self.assertEqual(
            self.result("simple_interest", loan("1000", "6", "6")),
            {
                "interest_usd": "30.00",
                "principal_plus_interest_usd": "1030.00",
                "term_months": "6",
            },
        )
        # 1 × 6% / 12 = half a cent, explicitly rounded up to a cent.
        self.assertEqual(
            self.result("simple_interest", loan("1", "6", "1"))["interest_usd"], "0.01"
        )
        # 1234.56 × .05125 × 1.5 = 94.9068 before cent rounding.
        self.assertEqual(
            self.result("simple_interest", loan("1234.56", "5.125", "18"))[
                "interest_usd"
            ],
            "94.91",
        )

    def test_zero_interest_and_maximum_bounded_simple_illustration(self):
        self.assertEqual(
            self.result("simple_interest", loan("10", "0", "600"))["interest_usd"],
            "0.00",
        )
        value = self.result("simple_interest", loan("1000000000000.00", "100", "600"))
        self.assertEqual(
            (value["interest_usd"], value["principal_plus_interest_usd"]),
            ("50000000000000.00", "51000000000000.00"),
        )

    def test_three_payment_loan_matches_hand_worked_cent_schedule(self):
        # Monthly rate 1%: interest 1.00, .67, .34; balances 67.00,33.67,0.
        value = self.result("amortizing_loan_payment", loan())
        self.assertEqual(
            value,
            {
                "scheduled_monthly_payment_usd": "34.00",
                "first_payment_usd": "34.00",
                "final_payment_usd": "34.01",
                "total_principal_usd": "100.00",
                "total_interest_usd": "2.01",
                "total_payments_usd": "102.01",
                "remaining_balance_usd": "0.00",
                "requested_term_months": "3",
                "months_elapsed": "3",
                "paid_off_early": False,
                "final_payment_adjusted": True,
            },
        )

    def test_two_payment_loan_matches_independent_known_interest_amounts(self):
        # Payment 507.51; first interest10.00 leaves502.49; last interest5.02.
        value = self.result("amortizing_loan_payment", loan("1000", "12", "2"))
        self.assertEqual(
            (
                value["scheduled_monthly_payment_usd"],
                value["final_payment_usd"],
                value["total_interest_usd"],
                value["total_payments_usd"],
            ),
            ("507.51", "507.51", "15.02", "1015.02"),
        )

    def test_zero_rate_loan_rounds_final_payment_and_clears_balance(self):
        value = self.result("amortizing_loan_payment", loan("100", "0", "3"))
        self.assertEqual(
            (
                value["scheduled_monthly_payment_usd"],
                value["final_payment_usd"],
                value["total_interest_usd"],
                value["total_payments_usd"],
                value["remaining_balance_usd"],
            ),
            ("33.33", "33.34", "0.00", "100.00", "0.00"),
        )
        large_term = self.result("amortizing_loan_payment", loan("100000", "0", "600"))
        self.assertEqual(
            (
                large_term["scheduled_monthly_payment_usd"],
                large_term["final_payment_usd"],
                large_term["months_elapsed"],
            ),
            ("166.67", "164.67", "600"),
        )

    def test_rounding_can_pay_off_early_and_half_cent_interest_is_explicit(self):
        early = self.result("amortizing_loan_payment", loan("0.01", "0", "2"))
        self.assertEqual(
            (
                early["months_elapsed"],
                early["paid_off_early"],
                early["total_payments_usd"],
            ),
            ("1", True, "0.01"),
        )
        half_cent = self.result("amortizing_loan_payment", loan("1", "6", "1"))
        self.assertEqual(
            (half_cent["final_payment_usd"], half_cent["total_interest_usd"]),
            ("1.01", "0.01"),
        )

    def test_unrepresentable_cent_payments_abstain_instead_of_hiding_a_balloon(self):
        for parameters, expected in (
            (loan("0.01", "0", "600"), "finance_payment_below_cent"),
            (loan("1000", "100", "600"), "finance_rounding_prevents_amortization"),
        ):
            with (
                self.subTest(category=expected),
                self.assertRaises(FinanceDenied) as error,
            ):
                self.result("amortizing_loan_payment", parameters)
            self.assertEqual(str(error.exception), expected)

    def test_percentage_change_has_signed_difference_and_explicit_positive_baseline(
        self,
    ):
        parameters = {
            "currency": "USD",
            "previous_usd": "100",
            "current_usd": "75",
            "period": "month",
        }
        self.assertEqual(
            self.result("percent_change", parameters),
            {
                "difference_usd": "-25.00",
                "percent_change": "-25.000000",
                "period": "month",
            },
        )
        self.assertEqual(
            self.result(
                "percent_change", parameters | {"previous_usd": "3", "current_usd": "4"}
            )["percent_change"],
            "33.333333",
        )
        self.assertEqual(
            self.result(
                "percent_change",
                parameters | {"previous_usd": "1", "current_usd": "-1"},
            )["percent_change"],
            "-200.000000",
        )

    def test_liquidity_ratio_and_shortfall_are_arithmetic_not_a_regulatory_metric(self):
        parameters = {
            "currency": "USD",
            "available_liquidity_usd": "150",
            "projected_outflows_usd": "100",
            "period": "day",
        }
        self.assertEqual(
            self.result("liquidity_coverage", parameters),
            {
                "coverage_ratio": "1.500000",
                "surplus_or_shortfall_usd": "50.00",
                "covers_stated_outflows": True,
                "period": "day",
            },
        )
        value = self.result(
            "liquidity_coverage",
            parameters
            | {"available_liquidity_usd": "1", "projected_outflows_usd": "3"},
        )
        self.assertEqual(
            (
                value["coverage_ratio"],
                value["surplus_or_shortfall_usd"],
                value["covers_stated_outflows"],
            ),
            ("0.333333", "-2.00", False),
        )

    def test_coverage_explains_the_cent_difference_when_the_ratio_rounds_to_one(self):
        cases = (
            (
                "999999.99",
                "-0.01",
                False,
                "falls short of the stated outflows by 0.01 USD",
            ),
            ("1000000.00", "0.00", True, "exactly matches the stated outflows"),
            ("1000000.01", "0.01", True, "exceeds the stated outflows by 0.01 USD"),
        )
        for cash, difference, covered, explanation in cases:
            with self.subTest(cash=cash):
                reply = calculate_finance(
                    "liquidity_coverage",
                    {
                        "currency": "USD",
                        "period": "day",
                        "available_liquidity_usd": cash,
                        "projected_outflows_usd": "1000000",
                    },
                )
                self.assertEqual(reply["result"]["coverage_ratio"], "1.000000")
                self.assertEqual(
                    reply["result"]["surplus_or_shortfall_usd"], difference
                )
                self.assertIs(reply["result"]["covers_stated_outflows"], covered)
                self.assertIn(explanation, reply["explanation"])
                self.assertIn("1.000000, rounded", reply["explanation"])

    def test_reconciliation_sign_convention_and_signed_opening_balance(self):
        parameters = {
            "currency": "USD",
            "opening_balance_usd": "1000",
            "credits_usd": "500",
            "debits_usd": "125",
            "reported_closing_balance_usd": "1370",
            "period": "statement",
        }
        self.assertEqual(
            self.result("reconciliation", parameters),
            {
                "expected_closing_balance_usd": "1375.00",
                "reported_closing_balance_usd": "1370.00",
                "reported_less_expected_usd": "-5.00",
                "balanced": False,
                "period": "statement",
            },
        )
        value = self.result(
            "reconciliation",
            parameters
            | {
                "opening_balance_usd": "-10",
                "credits_usd": "5",
                "debits_usd": "2",
                "reported_closing_balance_usd": "-7",
            },
        )
        self.assertTrue(value["balanced"])
        self.assertEqual(value["reported_less_expected_usd"], "0.00")

    def test_invalid_numbers_types_unicode_and_budgets_emit_only_fixed_categories(self):
        invalid = (
            True,
            False,
            1,
            1.0,
            None,
            {},
            [],
            "NaN",
            "Infinity",
            "-Infinity",
            "1e2",
            "1E999999999",
            "1_000",
            "1,000",
            "+1",
            " 1",
            "1 ",
            "01",
            "-0",
            "-0.00",
            "0.001",
            "1000000000000.01",
            "9" * 100000,
            "\uff11",
            "1\n",
            "1\u200b",
            "\ud800",
        )
        for value in invalid:
            with (
                self.subTest(type=type(value).__name__),
                self.assertRaises(FinanceDenied) as error,
            ):
                self.result("simple_interest", loan() | {"principal_usd": value})
            self.assertRegex(str(error.exception), r"^finance_[a-z_]+$")
            self.assertLess(len(str(error.exception)), 64)

    def test_rates_terms_denominators_currency_and_unknown_fields_are_closed(self):
        for changes in (
            {"annual_rate_percent": "-1"},
            {"annual_rate_percent": "100.000001"},
            {"annual_rate_percent": "0.0000001"},
            {"annual_rate_percent": "1e2"},
            {"term_months": "0"},
            {"term_months": "601"},
            {"term_months": "1.5"},
            {"term_months": True},
            {"currency": "EUR"},
            {"currency": "USD\n"},
            {"role": "bank_administrator"},
            {"formula": "__import__('os')"},
            {"principal_usd": "0"},
        ):
            with self.subTest(fields=list(changes)), self.assertRaises(FinanceDenied):
                self.result("amortizing_loan_payment", loan() | changes)
        for operation, parameters in (
            (
                "percent_change",
                {
                    "currency": "USD",
                    "previous_usd": "0",
                    "current_usd": "1",
                    "period": "month",
                },
            ),
            (
                "liquidity_coverage",
                {
                    "currency": "USD",
                    "available_liquidity_usd": "1",
                    "projected_outflows_usd": "0",
                    "period": "day",
                },
            ),
            (
                "percent_change",
                {
                    "currency": "USD",
                    "previous_usd": "1",
                    "current_usd": "2",
                    "period": "bank_policy_default",
                },
            ),
        ):
            with self.subTest(operation=operation), self.assertRaises(FinanceDenied):
                self.result(operation, parameters)
        for operation in (
            True,
            None,
            [],
            "eval",
            "approve_loan",
            "simple_interest\u0000",
        ):
            with (
                self.subTest(type=type(operation).__name__),
                self.assertRaises(FinanceDenied),
            ):
                calculate_finance(operation, loan())

    def test_output_is_bounded_explicit_and_independent_of_callers_decimal_context(
        self,
    ):
        parameters = loan()
        expected = calculate_finance("amortizing_loan_payment", parameters)
        with localcontext() as context:
            context.prec = 3
            self.assertEqual(
                calculate_finance("amortizing_loan_payment", parameters), expected
            )
        self.assertLess(len(encode(expected)), 32768)
        self.assertEqual(expected["currency"], "USD")
        self.assertEqual(expected["rounding"]["mode"], "ROUND_HALF_UP")
        self.assertFalse(
            expected["bank_quote"]
            or expected["approval_recorded"]
            or expected["execution_enabled"]
        )
        self.assertFalse(expected["provenance"]["external_data_used"])
        self.assertTrue(expected["explanation"] and expected["assumptions"])
        parameters["principal_usd"] = "999"
        self.assertEqual(expected["inputs"]["principal_usd"], "100")


if __name__ == "__main__":
    unittest.main()
