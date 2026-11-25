"""Check explicit input identifiers against the employee's authorized column catalog."""

import re

from nl2sql.schema import Schema

_NAME = r"[A-Za-z][A-Za-z0-9_]{0,62}"
_PATH = rf"(?:(?:public\.)?{_NAME}\.)?{_NAME}"
_START = r"\b(?:use|using|from|with|in|by|on|read|require|requires)\s+(?:the\s+)?"
_QUOTE = r"""["'\x60]?"""
_END = r"(?![\w/@]|[.-]\w)"
_MARKED = (
    re.compile(
        _START
        + rf"(?:input\s+)?(?:column|field)\s+(?:(?P<named>named|called)\s+)?{_QUOTE}(?P<ref>{_PATH}){_END}{_QUOTE}",
        re.I,
    ),
    re.compile(
        _START + rf"{_QUOTE}(?P<ref>{_PATH}){_QUOTE}\s+(?:column|field)\b", re.I
    ),
)
# A table-qualified identifier can serve as the subject, object or predicate
# of a question. Its grammar comes from the catalog, not English word order.
_DOTTED = re.compile(
    rf"(?<![\w@./-])(?P<ref>(?:public\.)?{_NAME}\.{_NAME}){_END}",
    re.I,
)
_LITERAL = re.compile(
    r"""(?<!\w)'[^'\r\n]*'|"[^"\r\n]*"|[“‘][^”’\r\n]*[”’]|https?://\S+|\S+@\S+""",
    re.I,
)
# SQL-like predicates may use unquoted examples, and a bare website or file
# name can look exactly like a qualified column. Leave those to the planner.
_VALUE_PREFIX = re.compile(
    r"(?:[=<>]|\b(?:equals?|matches|contains|ends? in|starts? with|"
    r"label(?:led)?|as|named|called|named the output|file|domain|host|website|url))\s*$",
    re.I,
)
_DOCUMENT_SUFFIXES = {
    "csv",
    "tsv",
    "parquet",
    "json",
    "xml",
    "xlsx",
    "xls",
    "pdf",
    "txt",
    "com",
    "net",
    "org",
    "edu",
    "gov",
    "io",
    "us",
}
_CONDITIONAL = re.compile(
    r"\b(?:if|or|optional(?:ly)?|otherwise|instead|without|unless|except|rather|"
    r"alternative|possibly|when available|where available|when possible|"
    r"alias(?:ed)?|computed|derived|derive|rename|fallback)\b",
    re.I,
)
_OMIT = re.compile(
    r"\b(?:skip|ignore|ignoring|omit|leave out|exclude|avoid|disregard|unneeded|"
    r"unnecessary|unused|no need|not (?:needed|required|necessary)|"
    r"(?:not|never|don['’]t) (?:need|want|use|include|require|select|show))\b",
    re.I,
)
_CLAUSES = re.compile(
    r"(?<=[?!;\n])|(?<=\.)(?=\s)|\b(?:but|however)\b|(?=\beven if\b)", re.I
)
_ANAPHOR = re.compile(
    r"\b(?:it|that (?:one|field|column|attribute)|this (?:field|column))\b", re.I
)
_REQUEST = re.compile(
    r"^\s*(?:please\s+)?(?:show|list|give|return|print|display|compute|calculate|group|filter|rank|"
    r"count|sum|total|read|use|using|find|summari[sz]e|tell|compare|select|retrieve|is|are|how|what|which|who|can you|could you)\b"
    r"|\b(?:I|we)\s+(?:need|require|want)\b|,\s*(?:please\s+)?(?:show|list|use|count|return|group|rank|find|calculate)\b",
    re.I,
)
_DESCRIPTIVE = re.compile(
    r"\b(?:example|hypothetical|historical(?:ly)?|formerly|previously|once|used to|deprecated|retired|for reference)\b",
    re.I,
)


def _present(reference: str, schema: Schema) -> bool:
    parts = reference.lower().removeprefix("public.").split(".")
    tables = schema.tables.values()
    if len(parts) == 2:
        table = schema.tables.get(parts[0])
        if table is None:
            return False
        tables = (table,)
    return any(column.name == parts[-1] for table in tables for column in table.columns)


def unavailable_named_field(question: str, schema: Schema) -> str | None:
    """Resolve required source fields, leaving descriptions and possible alternatives to SQL planning."""
    if len(question) > 2000:
        return None
    masked = _LITERAL.sub(lambda m: " " * len(m[0]), question)
    clauses = []
    start = 0
    for boundary in _CLAUSES.finditer(masked):
        if fragment := question[start : boundary.start()].strip():
            clauses.append(fragment)
        start = boundary.end()
    if fragment := question[start:].strip():
        clauses.append(fragment)
    for i, clause in enumerate(clauses):
        outside_literals = _LITERAL.sub(" ", clause)
        if (
            not _REQUEST.search(outside_literals)
            or _DESCRIPTIVE.search(outside_literals)
            or _CONDITIONAL.search(outside_literals)
            or _OMIT.search(outside_literals)
        ):
            continue
        if i + 1 < len(clauses):
            following = clauses[i + 1]
            if _OMIT.search(following) and _ANAPHOR.search(following):
                continue
        if missing := _missing_in_clause(clause, schema):
            return missing
    return None


def _missing_in_clause(question: str, schema: Schema) -> str | None:
    literals = [match.span() for match in _LITERAL.finditer(question)]
    for pattern in _MARKED:
        for match in pattern.finditer(question):
            if any(start <= match.start() < end for start, end in literals):
                continue
            reference = match["ref"]
            explicit = (
                "." in reference or "_" in reference or match.groupdict().get("named")
            )
            if explicit and not _present(reference, schema):
                return reference
    prose = _LITERAL.sub(" ", question)
    for match in _DOTTED.finditer(prose):
        reference = match["ref"]
        table, field = reference.lower().removeprefix("public.").split(".")
        if (
            table in schema.tables
            and field not in _DOCUMENT_SUFFIXES
            and not _VALUE_PREFIX.search(prose[: match.start()])
            and not _present(reference, schema)
        ):
            return reference
    return None
