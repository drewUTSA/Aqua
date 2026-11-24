"""Deterministic USD illustrations; no quotes, decisions, transport or execution."""

from decimal import Context, Decimal, DecimalException, ROUND_HALF_UP, localcontext
from fractions import Fraction
import re

from eval.banking.data import BankingDenied, encode, fields, require

CENT = Decimal("0.01")
SIX_PLACES = Decimal("0.000001")
MAX_AMOUNT = Decimal("1000000000000.00")
PERIODS = frozenset({"day", "month", "quarter", "year", "statement"})
DAY_BASES = {"Actual/360": 360, "Actual/365 Fixed": 365}
INPUT_FIELDS = {
    "simple_interest": {
        "currency",
        "principal_usd",
        "annual_rate_percent",
        "term_months",
    },
    "amortizing_loan_payment": {
        "currency",
        "principal_usd",
        "annual_rate_percent",
        "term_months",
    },
    "simple_interest_actual_days": {
        "currency",
        "principal_usd",
        "annual_rate_percent",
        "elapsed_days",
        "day_count_basis",
    },
    "percent_change": {"currency", "previous_usd", "current_usd", "period"},
    "liquidity_coverage": {
        "currency",
        "available_liquidity_usd",
        "projected_outflows_usd",
        "period",
    },
    "reconciliation": {
        "currency",
        "opening_balance_usd",
        "credits_usd",
        "debits_usd",
        "reported_closing_balance_usd",
        "period",
    },
}
ERRORS = frozenset(
    {
        "finance_operation",
        "finance_parameters",
        "finance_currency",
        "finance_period",
        "finance_amount",
        "finance_rate",
        "finance_term",
        "finance_positive_amount",
        "finance_nonnegative_amount",
        "finance_payment_below_cent",
        "finance_rounding_prevents_amortization",
        "finance_balance_invariant",
    }
)


class FinanceDenied(BankingDenied):
    """A fixed category, without input content or private calculation values."""


def money(value, *, signed=False, positive=False):
    require(
        type(value) is str
        and 0 < len(value) <= 17
        and re.fullmatch(r"-?(?:0|[1-9][0-9]{0,12})(?:\.[0-9]{1,2})?", value),
        "finance_amount",
    )
    result = Decimal(value)
    require(
        abs(result) <= MAX_AMOUNT and not (result.is_zero() and result.is_signed()),
        "finance_amount",
    )
    require(signed or result >= 0, "finance_nonnegative_amount")
    require(not positive or result > 0, "finance_positive_amount")
    return result.quantize(CENT)


def rate(value):
    require(
        type(value) is str
        and 0 < len(value) <= 10
        and re.fullmatch(r"(?:0|[1-9][0-9]{0,2})(?:\.[0-9]{1,6})?", value),
        "finance_rate",
    )
    result = Decimal(value)
    require(result <= 100, "finance_rate")
    return result


def months(value):
    require(
        type(value) is str
        and re.fullmatch(r"[1-9][0-9]{0,2}", value)
        and int(value) <= 600,
        "finance_term",
    )
    return int(value)


def usd(value):
    return format(value.quantize(CENT), ".2f")


def six(value):
    rounded = value.quantize(SIX_PLACES)
    return format(abs(rounded) if rounded.is_zero() else rounded, ".6f")


def loan_inputs(parameters):
    return (
        money(parameters["principal_usd"], positive=True),
        rate(parameters["annual_rate_percent"]),
        months(parameters["term_months"]),
    )


def simple_interest(parameters):
    principal, annual_rate, term = loan_inputs(parameters)
    interest = (principal * annual_rate * term / Decimal(1200)).quantize(CENT)
    return (
        {
            "interest_usd": usd(interest),
            "principal_plus_interest_usd": usd(principal + interest),
            "term_months": str(term),
        },
        f"Over {term} supplied months, simple interest is {usd(interest)} USD. Principal plus interest is {usd(principal + interest)} USD.",
        [
            "Simple interest is principal × annual rate (percent) × months / 1200.",
            "A month is one twelfth of a year; there is no compounding or day-count adjustment.",
            "Interest is rounded once to cents at the end; fees, taxes and bank product terms are excluded.",
        ],
    )


def simple_interest_actual_days(parameters):
    principal = money(parameters["principal_usd"], positive=True)
    annual_rate = rate(parameters["annual_rate_percent"])
    elapsed = parameters["elapsed_days"]
    basis = parameters["day_count_basis"]
    require(
        type(elapsed) is str
        and re.fullmatch(r"[1-9][0-9]{0,4}", elapsed)
        and int(elapsed) <= 18300,
        "finance_term",
    )
    require(type(basis) is str and basis in DAY_BASES, "finance_parameters")
    days, denominator = int(elapsed), DAY_BASES[basis]
    interest = (principal * annual_rate * days / (100 * denominator)).quantize(CENT)
    return (
        {
            "interest_usd": usd(interest),
            "principal_plus_interest_usd": usd(principal + interest),
            "elapsed_days": elapsed,
            "day_count_basis": basis,
            "year_fraction": f"{days}/{denominator}",
        },
        f"Over {days} elapsed days on {basis}, simple interest is {usd(interest)} USD using {days}/{denominator} of a year.",
        [
            "The employee supplies the actual elapsed calendar days and the fixed day-count denominator.",
            "Simple interest is principal × annual percentage / 100 × elapsed days / the stated denominator.",
            "Interest is rounded once to cents at the end. Fees, compounding and product-specific terms are excluded.",
        ],
    )


def amortizing_loan_payment(parameters):
    principal, annual_rate, term = loan_inputs(parameters)
    # The monthly rate can repeat in decimal. Keep it exact until the
    # scheduled payment is rounded to the nearest cent, including half cents.
    monthly_rate = Fraction(annual_rate) / 1200
    principal_cents = int(principal * 100)
    if monthly_rate:
        growth = (1 + monthly_rate) ** term
        payment_cents = principal_cents * monthly_rate * growth / (growth - 1)
    else:
        payment_cents = Fraction(principal_cents, term)
    whole, remainder = divmod(payment_cents.numerator, payment_cents.denominator)
    payment = Decimal(whole + int(2 * remainder >= payment_cents.denominator)).scaleb(
        -2
    )

    def interest_due(balance):
        # Multiply before dividing so an exact half cent stays on the boundary.
        return (balance * annual_rate / Decimal(1200)).quantize(CENT)

    require(payment > 0, "finance_payment_below_cent")
    require(
        payment > interest_due(principal),
        "finance_rounding_prevents_amortization",
    )
    balance, interest_total, payment_total, principal_total = (
        principal,
        Decimal(0),
        Decimal(0),
        Decimal(0),
    )
    first_payment = final_payment = Decimal(0)
    elapsed = 0
    for elapsed in range(1, term + 1):
        interest = interest_due(balance)
        due = balance + interest
        actual = due if elapsed == term or due <= payment else payment
        principal_paid = actual - interest
        require(
            principal_paid > 0 and principal_paid <= balance,
            "finance_balance_invariant",
        )
        balance -= principal_paid
        principal_total += principal_paid
        interest_total += interest
        payment_total += actual
        if elapsed == 1:
            first_payment = actual
        final_payment = actual
        if balance == 0:
            break
    require(
        balance == 0
        and principal_total == principal
        and payment_total == principal + interest_total,
        "finance_balance_invariant",
    )
    result = {
        "scheduled_monthly_payment_usd": usd(payment),
        "first_payment_usd": usd(first_payment),
        "final_payment_usd": usd(final_payment),
        "total_principal_usd": usd(principal_total),
        "total_interest_usd": usd(interest_total),
        "total_payments_usd": usd(payment_total),
        "remaining_balance_usd": usd(balance),
        "requested_term_months": str(term),
        "months_elapsed": str(elapsed),
        "paid_off_early": elapsed < term,
        "final_payment_adjusted": final_payment != payment,
    }
    explanation = f"The illustrated monthly payment is {usd(payment)} USD. After monthly cent rounding, the final payment is {usd(final_payment)} USD and total interest is {usd(interest_total)} USD."
    if elapsed < term:
        explanation += f" Cent rounding pays this illustration off in {elapsed} months."
    return (
        result,
        explanation,
        [
            "The fixed nominal annual rate, expressed as a percentage, is divided by 12; monthly payments occur at period end.",
            "The ordinary annuity formula determines the scheduled payment; a zero rate uses principal / months.",
            "Each month's interest and payment are rounded to cents; the last payment clears the exact remaining cent balance.",
            "No fees, taxes, insurance, day-count adjustment, changing rates, prepayments or bank product terms are included.",
            "Inputs whose cent-rounded payment cannot amortize principal are declined rather than shown as a loan quote.",
        ],
    )


def percent_change(parameters):
    previous = money(parameters["previous_usd"], positive=True)
    current = money(parameters["current_usd"], signed=True)
    difference = current - previous
    percentage = difference * 100 / previous
    return (
        {
            "difference_usd": usd(difference),
            "percent_change": six(percentage),
            "period": parameters["period"],
        },
        f"The change is {usd(difference)} USD, or {six(percentage)}% of the supplied positive baseline.",
        [
            "Percent change is (current − previous) / previous × 100.",
            "The caller supplies comparable observations in chronological order with the same period definition.",
            "A zero or negative baseline is declined; a negative current amount is allowed.",
        ],
    )


def liquidity_coverage(parameters):
    available = money(parameters["available_liquidity_usd"])
    outflows = money(parameters["projected_outflows_usd"], positive=True)
    difference = available - outflows
    ratio = six(available / outflows)
    if difference < 0:
        coverage = f"Available cash falls short of the stated outflows by {usd(-difference)} USD."
    elif difference > 0:
        coverage = (
            f"Available cash exceeds the stated outflows by {usd(difference)} USD."
        )
    else:
        coverage = "Available cash exactly matches the stated outflows."
    return (
        {
            "coverage_ratio": ratio,
            "surplus_or_shortfall_usd": usd(difference),
            "covers_stated_outflows": difference >= 0,
            "period": parameters["period"],
        },
        f"{coverage} The cash-to-outflows ratio for the supplied {parameters['period']} period is {ratio}, rounded to six decimal places.",
        [
            "Coverage is supplied available liquidity / supplied projected outflows for the same period.",
            "No eligibility, regulatory weighting, stress assumptions or approved bank liquidity limit is supplied.",
            "This arithmetic illustration does not calculate a regulatory liquidity coverage ratio.",
        ],
    )


def reconciliation(parameters):
    opening = money(parameters["opening_balance_usd"], signed=True)
    credits = money(parameters["credits_usd"])
    debits = money(parameters["debits_usd"])
    reported = money(parameters["reported_closing_balance_usd"], signed=True)
    expected = opening + credits - debits
    difference = reported - expected
    return (
        {
            "expected_closing_balance_usd": usd(expected),
            "reported_closing_balance_usd": usd(reported),
            "reported_less_expected_usd": usd(difference),
            "balanced": difference == 0,
            "period": parameters["period"],
        },
        f"Opening balance plus credits less debits gives {usd(expected)} USD. Reported less expected is {usd(difference)} USD.",
        [
            "Credits increase and debits decrease the supplied balance under this illustration's sign convention.",
            "All amounts must describe the same account scope, USD currency and supplied period.",
            "A zero difference is arithmetic agreement; records, completeness and authorization are not independently verified.",
        ],
    )


OPERATIONS = {
    "simple_interest": simple_interest,
    "simple_interest_actual_days": simple_interest_actual_days,
    "amortizing_loan_payment": amortizing_loan_payment,
    "percent_change": percent_change,
    "liquidity_coverage": liquidity_coverage,
    "reconciliation": reconciliation,
}


def calculate_finance(operation: str, parameters: dict) -> dict:
    """Calculate a bounded illustration with explicit units and fixed errors."""
    try:
        require(
            type(operation) is str
            and 0 < len(operation) <= 32
            and operation in OPERATIONS,
            "finance_operation",
        )
        require(
            type(parameters) is dict
            and len(parameters) <= 6
            and all(type(key) is str for key in parameters),
            "finance_parameters",
        )
        fields(parameters, INPUT_FIELDS[operation], "finance_parameters")
        require(
            type(parameters["currency"]) is str and parameters["currency"] == "USD",
            "finance_currency",
        )
        if "period" in parameters:
            require(
                type(parameters["period"]) is str and parameters["period"] in PERIODS,
                "finance_period",
            )
        with localcontext(
            Context(prec=60, rounding=ROUND_HALF_UP, Emin=-999, Emax=999)
        ):
            result, explanation, assumptions = OPERATIONS[operation](parameters)
        response = {
            "schemaVersion": 1,
            "status": "calculated",
            "operation": operation,
            "currency": "USD",
            "inputs": dict(parameters),
            "result": result,
            "explanation": explanation,
            "assumptions": assumptions,
            "rounding": {
                "mode": "ROUND_HALF_UP",
                "money_decimals": 2,
                "percent_and_ratio_decimals": 6,
                "working_precision_digits": 60,
            },
            "provenance": {
                "kind": "deterministic_calculation",
                "input_source": "caller_supplied_illustration",
                "formula_version": "aqua-demo-finance-v1",
                "external_data_used": False,
            },
            "bank_quote": False,
            "approval_recorded": False,
            "execution_enabled": False,
        }
        encode(response)
        return response
    except BankingDenied as error:
        category = (
            error.args[0]
            if error.args and error.args[0] in ERRORS
            else "finance_invalid_input"
        )
        raise FinanceDenied(category) from None
    except DecimalException:
        raise FinanceDenied("finance_arithmetic_unavailable") from None
