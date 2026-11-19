"""Resolve standalone calendar counts against the reviewed bank event dates."""

import re
from datetime import date, timedelta

from nl2sql.metadata_policy import BANK_TABLES
from nl2sql.schema import Schema

_MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_MONTH_NUMBER = {
    name: i for i, month in enumerate(_MONTHS, 1) for name in (month, month[:3])
}
_COUNT = re.compile(
    r"(?:please )?(?:how many|count(?: the)?|what (?:is|was) the number of|"
    r"show(?: me)? the number of) (.+)"
)
# Require an event for entities that could also mean an outstanding balance or
# an active population. Only the fixed identifiers below can appear in SQL.
_EVENTS = (
    (
        r"transactions(?: (?:were (?:there|posted|recorded)|posted|occurred))?",
        "trans",
        "date",
        "transaction_count",
    ),
    (r"(?:bank )?accounts (?:were )?opened", "account", "date", "account_count"),
    (r"loans (?:were )?granted", "loan", "date", "loan_count"),
    (r"(?:credit )?cards (?:were )?issued", "card", "issued", "card_count"),
)


def _period(preposition: str, period: str) -> tuple[date, date] | None:
    """Half-open Gregorian dates. Both endpoints must be representable."""
    if preposition == "on":
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", period):
            return None
        start = date.fromisoformat(period)
        return start, start + timedelta(days=1)

    if match := re.fullmatch(r"(?:calendar year )?([0-9]{4})", period):
        year = int(match[1])
        return date(year, 1, 1), date(year + 1, 1, 1)
    if match := re.fullmatch(
        r"calendar (?:q|quarter )([1-4]) (?:of )?([0-9]{4})", period
    ):
        month, year, duration = 3 * int(match[1]) - 2, int(match[2]), 3
    elif match := re.fullmatch(r"([a-z]+) ([0-9]{4})", period):
        month = _MONTH_NUMBER.get(match[1])
        if month is None:
            return None
        year, duration = int(match[2]), 1
    elif match := re.fullmatch(r"([0-9]{4})-([0-9]{2})", period):
        year, month, duration = int(match[1]), int(match[2]), 1
    else:
        return None
    start = date(year, month, 1)
    next_year, next_month = divmod(month - 1 + duration, 12)
    return start, date(year + next_year, next_month + 1, 1)


def calendar_count_sql(
    question: str, schema: Schema, selected: tuple[str, ...]
) -> str | None:
    """Recognize a complete count request. Other questions use normal generation."""
    if schema.allowed_tables != BANK_TABLES or len(question) > 256:
        return None
    text = " ".join(question.lower().split()).removesuffix("?").removesuffix(".")
    if prefix := re.fullmatch(r"(on|in|during) ([^,]+), (.+)", text):
        preposition, period, request = prefix.groups()
    elif suffix := re.fullmatch(r"(.+) (on|in|during) (.+)", text):
        request, preposition, period = suffix.groups()
    else:
        return None
    count = _COUNT.fullmatch(request)
    if not count:
        return None
    try:
        bounds = _period(preposition, period)
    except (OverflowError, ValueError):
        return None
    if bounds is None:
        return None
    for event, table, field, alias in _EVENTS:
        if re.fullmatch(event, count[1]) and table in selected:
            if any(
                c.name == field and c.type == "date"
                for c in schema.tables[table].columns
            ):
                start, end = bounds
                return (
                    f"SELECT COUNT(*) AS {alias} FROM {table} "
                    f"WHERE {field} >= DATE '{start.isoformat()}' AND {field} < DATE '{end.isoformat()}'"
                )
    return None
