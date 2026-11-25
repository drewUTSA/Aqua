"""Closed diagnostics: database/provider text is never a public repair hint."""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Diagnostic:
    message: str
    fixable: bool = False


DIAGNOSTICS = {
    "missing_source": Diagnostic(
        "Which connected field or source supplies the missing information for this question?"
    ),
    "ranking_request_invalid": Diagnostic(
        "Start a new chat and use Rank groups with one source, one group field, "
        "and either row count or the total of one numeric field."
    ),
    "query_failed": Diagnostic("The database could not complete this query."),
    "invalid_column": Diagnostic(
        "A query column does not exist. Use only the supplied schema columns.", True
    ),
    "invalid_query": Diagnostic(
        "The query syntax or types are invalid. Check the supplied schema and SQL syntax.",
        True,
    ),
    "timeout": Diagnostic(
        "The query exceeded the statement timeout. Ask for a narrower result."
    ),
    "access_denied": Diagnostic("The query is not permitted for this dataset."),
    "rejected": Diagnostic("The query was rejected by the read-only data policy."),
    "repair_query": Diagnostic(
        "Use one read-only SELECT with only the supplied tables and named visible columns.",
        True,
    ),
}


def diagnostic(code: str) -> Diagnostic:
    """Unknown text cannot become a hint, even if a caller passes an exception."""
    return DIAGNOSTICS.get(code, DIAGNOSTICS["query_failed"])


def query_code(sqlstate: str | None) -> str:
    """Classify by PostgreSQL's nonlocalized code, never parse error values."""
    if sqlstate == "42703":
        return "invalid_column"
    if sqlstate in {"42601", "42883", "42804", "42803", "42846", "22P02", "22012"}:
        return "invalid_query"
    if sqlstate == "57014":
        return "timeout"
    if sqlstate in {"42501", "25006", "28000", "28P01", "42P01", "3F000"}:
        return "access_denied"
    return "query_failed"


def public_query_error(code: str | None, message: str | None) -> str:
    """Defense in depth if a future pipeline supplies an unsanitized error."""
    known = {item.message for item in DIAGNOSTICS.values()}
    return message if message in known else diagnostic(code or "query_failed").message


def missing_source_message(question: str, label: str | None) -> str:
    """Only repeat a bounded phrase the employee supplied, never provider text."""
    if (
        not label
        or len(label) > 195
        or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_]{0,62}(?:\.[A-Za-z][A-Za-z0-9_]{0,62}){0,2}", label
        )
    ):
        return diagnostic("missing_source").message
    match = re.search(
        r"(?<![\w@.])" + re.escape(label) + r"(?!\w|[@.]\w)", question, re.I
    )
    if not match:
        return diagnostic("missing_source").message
    return f"I couldn't identify a source for “{match.group()}” in the connected data. Which field or source supplies it?"


class ContextDenied(RuntimeError):
    """Retrieval or metadata is outside the authorized dataset; never widen."""


class RetrievalUnavailable(RuntimeError):
    """Explicit availability failure permits the same authorized schema fallback."""
