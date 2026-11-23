"""Discoverable calculator metadata; finance.py independently validates inputs."""

from copy import deepcopy


def exact_pattern(body):
    # Unlike a bare $, this portable end assertion also rejects a final newline.
    return r"^(?:" + body + r")(?![\s\S])"


AMOUNT = r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,2})?|1000000000000(?:\.0{1,2})?"
RATE = r"(?:0|[1-9][0-9]?)(?:\.[0-9]{1,6})?|100(?:\.0{1,6})?"
TERM = r"[1-9]|[1-9][0-9]|[1-5][0-9]{2}|600"
PERIODS = ["day", "month", "quarter", "year", "statement"]


def amount(description, *, positive=False, signed=False):
    value = {
        "type": "string",
        "minLength": 1,
        "maxLength": 17,
        "pattern": exact_pattern(r"-?(?:" + AMOUNT + ")" if signed else AMOUNT),
        "description": description
        + " Plain USD decimal text, at most two fractional digits and an absolute maximum of 1000000000000.00; no exponent, separators or whitespace.",
    }
    if positive:
        value["not"] = {"enum": ["0", "0.0", "0.00"]}
    elif signed:
        value["not"] = {"enum": ["-0", "-0.0", "-0.00"]}
    return value


CURRENCY = {
    "type": "string",
    "const": "USD",
    "description": "USD only; no currency conversion.",
}
PERIOD = {
    "type": "string",
    "enum": PERIODS,
    "description": "The same supplied period definition must apply to all compared amounts.",
}
LOAN = {
    "currency": CURRENCY,
    "principal_usd": amount("Strictly positive principal.", positive=True),
    "annual_rate_percent": {
        "type": "string",
        "minLength": 1,
        "maxLength": 10,
        "pattern": exact_pattern(RATE),
        "description": "Nominal annual rate in percent, from 0 through 100 inclusive, at most six fractional digits; zero is supported. Plain numeric text only; fees and product APR terms are excluded.",
    },
    "term_months": {
        "type": "string",
        "minLength": 1,
        "maxLength": 3,
        "pattern": exact_pattern(TERM),
        "description": "Whole months from 1 through 600 inclusive, as plain integer text without leading zeros.",
    },
}

DEFINITIONS = {
    "simple_interest": (
        "Simple interest over the supplied whole months; no compounding or day-count adjustment.",
        LOAN,
        {
            "currency": "USD",
            "principal_usd": "1000.00",
            "annual_rate_percent": "6",
            "term_months": "12",
        },
    ),
    "amortizing_loan_payment": (
        "Fixed-rate, end-of-month payment illustration with ROUND_HALF_UP cents and an adjusted final payment; payments that cannot amortize after cent rounding are declined.",
        LOAN,
        {
            "currency": "USD",
            "principal_usd": "100.00",
            "annual_rate_percent": "12",
            "term_months": "3",
        },
    ),
    "percent_change": (
        "Change from a strictly positive previous USD amount to the current amount; supply comparable observations in chronological order.",
        {
            "currency": CURRENCY,
            "previous_usd": amount(
                "Strictly positive previous baseline.", positive=True
            ),
            "current_usd": amount(
                "Current amount; negative values are allowed.", signed=True
            ),
            "period": PERIOD,
        },
        {
            "currency": "USD",
            "previous_usd": "100.00",
            "current_usd": "75.00",
            "period": "month",
        },
    ),
    "liquidity_coverage": (
        "Available liquidity divided by stated projected outflows for the same period; this illustration is not a regulatory liquidity coverage ratio.",
        {
            "currency": CURRENCY,
            "available_liquidity_usd": amount("Nonnegative available liquidity."),
            "projected_outflows_usd": amount(
                "Strictly positive projected outflows.", positive=True
            ),
            "period": PERIOD,
        },
        {
            "currency": "USD",
            "available_liquidity_usd": "150.00",
            "projected_outflows_usd": "100.00",
            "period": "day",
        },
    ),
    "reconciliation": (
        "Expected closing = opening + credits - debits. Difference = reported closing - expected closing; use one consistent account scope and period.",
        {
            "currency": CURRENCY,
            "opening_balance_usd": amount(
                "Opening balance; negative values are allowed.", signed=True
            ),
            "credits_usd": amount("Nonnegative credits that increase the balance."),
            "debits_usd": amount("Nonnegative debits that decrease the balance."),
            "reported_closing_balance_usd": amount(
                "Reported closing balance; negative values are allowed.", signed=True
            ),
            "period": PERIOD,
        },
        {
            "currency": "USD",
            "opening_balance_usd": "1000.00",
            "credits_usd": "500.00",
            "debits_usd": "125.00",
            "reported_closing_balance_usd": "1370.00",
            "period": "statement",
        },
    ),
}


def with_finance_schema(schema):
    """Couple each operation to its exact closed parameter object in discovery."""
    # Some tool-calling clients display only the immediate object properties.
    # Keep the same field names visible there as in the full per-operation schema.
    fields = "\n".join(
        f"{operation}: {', '.join(k for k in properties if k != 'currency')}"
        for operation, (_, properties, _) in DEFINITIONS.items()
    )
    schema["properties"]["parameters"]["description"] = (
        "Supply a JSON object using the fields listed for the chosen operation. "
        "All values are strings. Supply currency exactly once on the request or inside parameters. "
        "Use plain numbers for amounts, whole months for terms and percentage points for annual rates. "
        f"When required, period is one of {', '.join(PERIODS)}.\n{fields}"
    )
    schema["properties"]["currency"] = deepcopy(CURRENCY)
    # Keep the original nested currency form for existing clients. Exactly one
    # location must declare the unit before either request reaches the calculator.
    nested_currency = {"properties": {"parameters": {"required": ["currency"]}}}
    schema["if"] = {"required": ["currency"]}
    schema["then"] = {"not": nested_currency}
    schema["else"] = nested_currency
    schema["oneOf"] = [
        {
            "title": operation,
            "description": description,
            "type": "object",
            "properties": {
                "operation": {"type": "string", "const": operation},
                "currency": deepcopy(CURRENCY),
                "parameters": {
                    "type": "object",
                    "properties": deepcopy(properties),
                    "required": [field for field in properties if field != "currency"],
                    "additionalProperties": False,
                    "maxProperties": len(properties),
                },
            },
            "required": ["operation", "parameters"],
            "additionalProperties": False,
            "examples": [{"operation": operation, "parameters": deepcopy(example)}],
        }
        for operation, (description, properties, example) in DEFINITIONS.items()
    ]
