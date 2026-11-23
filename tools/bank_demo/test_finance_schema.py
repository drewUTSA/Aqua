"""Actual SDK discovery exposes usable calculator contracts without coercion."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import anyio
from jsonschema import Draft202012Validator
from mcp import Client

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp_demo.finance import (
    INPUT_FIELDS,
    OPERATIONS,
    FinanceDenied,
    calculate_finance,
)  # noqa: E402
from mcp_demo.protocol import MAX_FRAME_BYTES, actor_for  # noqa: E402
from mcp_demo.server import FinanceArguments, build_server  # noqa: E402
from tools.bank_demo.test_demo_sdk import parameters  # noqa: E402


class FinanceDiscoveryTests(unittest.TestCase):
    def test_correctable_errors_give_public_guidance_only_after_scope(self):
        loan = {
            "currency": "USD",
            "principal_usd": "1300.11",
            "annual_rate_percent": "3.21",
            "term_months": "15",
        }
        canary = "nonpublic_employee_test_marker"
        missing = {key: val for key, val in loan.items() if key != "principal_usd"}
        cases = [
            (
                "simple_interest",
                {**loan, "currency": canary},
                "Declare currency exactly once",
            ),
            ("simple_interest", {**missing, canary: "900"}, "principal_usd"),
            (
                "simple_interest",
                {**loan, "annual_rate_percent": canary},
                "annual percentage",
            ),
            ("simple_interest", {**loan, "term_months": canary}, "whole-number"),
            (
                "percent_change",
                {
                    "currency": "USD",
                    "previous_usd": "710",
                    "current_usd": "810",
                    "period": canary,
                },
                "quarter",
            ),
            (
                "amortizing_loan_payment",
                {
                    **loan,
                    "principal_usd": "0.01",
                    "annual_rate_percent": "0",
                    "term_months": "600",
                },
                "withhold the illustration",
            ),
        ]

        async def check():
            for persona in ("none", "teller", "analyst", "manager"):
                async with Client(build_server(actor_for(persona))) as client:
                    generic = await client.call_tool("absent_tool", {})
                    for operation, operands, hint in cases:
                        result = await client.call_tool(
                            "calculate_finance",
                            {"operation": operation, "parameters": operands},
                        )
                        body = result.structured_content["data"]
                        self.assertTrue(result.is_error)
                        self.assertEqual(set(body), {"status", "reason", "message"})
                        self.assertEqual(body["status"], "denied")
                        self.assertEqual(body["reason"], "demo_request_denied")
                        self.assertNotIn(canary, result.model_dump_json())
                        self.assertNotIn("1300.11", result.model_dump_json())
                        if persona == "none":
                            self.assertEqual(body, generic.structured_content["data"])
                        else:
                            self.assertIn(hint, body["message"])
                    if persona == "none":
                        continue
                    request = {"operation": "simple_interest", "parameters": loan}
                    with patch(
                        "mcp_demo.server.finance.calculate_finance",
                        side_effect=FinanceDenied("finance_balance_invariant"),
                    ):
                        internal = await client.call_tool("calculate_finance", request)
                    self.assertEqual(
                        internal.structured_content, generic.structured_content
                    )
                    corrected = await client.call_tool("calculate_finance", request)
                    self.assertFalse(corrected.is_error)
                    self.assertEqual(
                        corrected.structured_content["data"]["result"]["interest_usd"],
                        "52.17",
                    )

        anyio.run(check)

    def test_day_errors_request_the_employee_basis_and_elapsed_days(self):
        daily = {
            "currency": "USD",
            "principal_usd": "1231.79",
            "annual_rate_percent": "4.25",
            "elapsed_days": "32",
            "day_count_basis": "Actual/360",
        }
        cases = [
            (
                {k: v for k, v in daily.items() if k != "day_count_basis"},
                "governing basis",
            ),
            ({**daily, "day_count_basis": "Actual/Actual ISDA"}, "governing basis"),
            (
                {k: v for k, v in daily.items() if k != "elapsed_days"},
                "actual elapsed calendar days",
            ),
            (
                {**daily, "elapsed_days": "calendar month"},
                "actual elapsed calendar days",
            ),
        ]

        async def check():
            for persona in ("teller", "none"):
                async with Client(build_server(actor_for(persona))) as client:
                    for params, expected in cases:
                        result = await client.call_tool(
                            "calculate_finance",
                            {
                                "operation": "simple_interest_actual_days",
                                "parameters": params,
                            },
                        )
                        self.assertTrue(result.is_error)
                        data = result.structured_content["data"]
                        self.assertEqual(data["reason"], "demo_request_denied")
                        self.assertNotIn("1231.79", result.model_dump_json())
                        if persona == "none":
                            self.assertNotIn(expected, data["message"])
                        else:
                            self.assertIn(expected, data["message"])

        anyio.run(check)

    def test_official_sdk_lists_coupled_closed_finance_schemas_within_frame_budget(
        self,
    ):
        async def check():
            async with Client(parameters("analyst")) as client:
                listed = await client.list_tools()
                self.assertLessEqual(
                    len(
                        listed.model_dump_json(
                            by_alias=True, exclude_none=True
                        ).encode()
                    )
                    + 512,
                    MAX_FRAME_BYTES,
                )
                tool = next(
                    tool for tool in listed.tools if tool.name == "calculate_finance"
                )
                schema = tool.input_schema
                Draft202012Validator.check_schema(schema)
                validator = Draft202012Validator(schema)
                branches = {
                    branch["properties"]["operation"]["const"]: branch
                    for branch in schema["oneOf"]
                }
                self.assertEqual(set(branches), set(OPERATIONS))
                parameter_help = schema["properties"]["parameters"]["description"]
                for operation, branch in branches.items():
                    required = branch["properties"]["parameters"]["required"]
                    self.assertIn(
                        f"{operation}: {', '.join(required)}",
                        parameter_help.splitlines(),
                    )
                examples = {}
                for operation, branch in branches.items():
                    with self.subTest(operation=operation):
                        properties = branch["properties"]["parameters"]
                        self.assertEqual(
                            set(properties["required"]),
                            INPUT_FIELDS[operation] - {"currency"},
                        )
                        self.assertEqual(
                            set(properties["properties"]), INPUT_FIELDS[operation]
                        )
                        self.assertFalse(properties["additionalProperties"])
                        example = deepcopy(branch["examples"][0])
                        examples[operation] = example
                        validator.validate(example)
                        self.assertEqual(
                            calculate_finance(**example)["status"], "calculated"
                        )
                        outside = deepcopy(example)
                        outside["currency"] = outside["parameters"].pop("currency")
                        validator.validate(outside)
                        installed = await client.call_tool("calculate_finance", outside)
                        original = await client.call_tool("calculate_finance", example)
                        self.assertFalse(installed.is_error)
                        self.assertEqual(
                            installed.structured_content, original.structured_content
                        )
                        duplicate = deepcopy(example)
                        duplicate["currency"] = "USD"
                        absent = deepcopy(outside)
                        del absent["currency"]
                        for denied in (
                            duplicate,
                            absent,
                            outside | {"currency": "GBP"},
                            outside | {"currency": None},
                        ):
                            self.assertFalse(validator.is_valid(denied))
                            self.assertTrue(
                                (
                                    await client.call_tool("calculate_finance", denied)
                                ).is_error
                            )
                        for name in properties["required"]:
                            missing = deepcopy(example)
                            del missing["parameters"][name]
                            self.assertFalse(validator.is_valid(missing), name)
                        for name in set(properties["required"]) - {
                            "currency",
                            "period",
                        }:
                            for bad in (
                                True,
                                1.25,
                                "NaN",
                                "Infinity",
                                "1e2",
                                "01",
                                "1\n",
                                "\uff11",
                            ):
                                invalid = deepcopy(example)
                                invalid["parameters"][name] = bad
                                self.assertFalse(validator.is_valid(invalid), name)
                        for location in ("parameters", "top"):
                            extra = deepcopy(example)
                            target = (
                                extra["parameters"]
                                if location == "parameters"
                                else extra
                            )
                            target["approved"] = True
                            self.assertFalse(validator.is_valid(extra))
                        foreign = deepcopy(example)
                        foreign["parameters"]["currency"] = "EUR"
                        self.assertFalse(validator.is_valid(foreign))
                        if "period" in example["parameters"]:
                            invalid_period = deepcopy(example)
                            invalid_period["parameters"]["period"] = "bank_default"
                            self.assertFalse(validator.is_valid(invalid_period))
                mismatched = deepcopy(examples["simple_interest"])
                mismatched["operation"] = "percent_change"
                self.assertFalse(validator.is_valid(mismatched))
                self.assertFalse(
                    validator.is_valid({"operation": "approve_loan", "parameters": {}})
                )
                base = deepcopy(examples["simple_interest"])
                for key, valid, invalid in (
                    ("principal_usd", "1000000000000.00", "1000000000000.01"),
                    ("annual_rate_percent", "100.000000", "100.000001"),
                    ("term_months", "600", "601"),
                ):
                    admitted = deepcopy(base)
                    admitted["parameters"][key] = valid
                    validator.validate(admitted)
                    admitted["parameters"][key] = invalid
                    self.assertFalse(validator.is_valid(admitted), key)
                zero = deepcopy(base)
                zero["parameters"]["principal_usd"] = "0.00"
                self.assertFalse(validator.is_valid(zero))
                signed = deepcopy(examples["percent_change"])
                signed["parameters"]["current_usd"] = "-1000000000000.00"
                validator.validate(signed)
                signed["parameters"]["current_usd"] = "-0.00"
                self.assertFalse(validator.is_valid(signed))

        async def bounded():
            with anyio.fail_after(10):
                await check()

        anyio.run(bounded)

    def test_schema_metadata_does_not_coerce_or_replace_runtime_validation(self):
        base = {
            "currency": "USD",
            "principal_usd": 1000.0,
            "annual_rate_percent": "6",
            "term_months": "12",
        }
        parsed = FinanceArguments.model_validate(
            {"operation": "simple_interest", "parameters": base}
        )
        self.assertIs(type(parsed.parameters["principal_usd"]), float)
        self.assertTrue(FinanceArguments.model_config["strict"])
        self.assertEqual(FinanceArguments.model_config["extra"], "forbid")
        with self.assertRaises(FinanceDenied):
            calculate_finance(parsed.operation, parsed.parameters)


if __name__ == "__main__":
    unittest.main()
