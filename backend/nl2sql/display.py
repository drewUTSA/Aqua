"""Make result tables readable, using the database's own comments.

The bank database stores codes (PRIJEM, loan status B) and unnamed
columns (a11). Its comments, written in db/financial/02_load.sql, say
what they mean. This module turns them into display rules:

- value labels: PRIJEM -> "Credit (money in)"
- column labels: a11 -> "Average salary"
- the currency, from a table comment such as "Amounts in Czech crowns (CZK)."

The comments are the only source, so nothing here names a bank table,
and a database without comments (Pagila) displays exactly as before.
The SQL the user sees still has the real codes.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from nl2sql.relations import projected_columns
from nl2sql.schema import Schema, Table, Column

# "CODE = meaning" pairs are separated by ", " or "; " (or follow a
# "Purpose: " lead-in) where the next piece is itself "... = ...".
# Meanings may contain commas: "A = finished, paid off; B = ...".
_PAIR_SPLIT = re.compile(r"[,;:] (?=[^,;:=]+ = )")
# Codes are upper case: PRIJEM, POPLATEK MESICNE, SANKC. UROK, B.
_CODE = re.compile(r"^[A-Z][A-Z.]*(?: [A-Z][A-Z.]*)*$")
# An ISO currency code in brackets, e.g. "(CZK)".
_CURRENCY = re.compile(r"\(([A-Z]{3})\)")

# A comment longer than this reads as a sentence, not a column header.
MAX_LABEL_LENGTH = 50

_OUTPUT = re.compile(
    r"\b(?:show|return|output|display|list|give|include|provide|report|plot|chart|what (?:is|are)|which|I (?:need|want)|tell me)\b",
    re.I,
)
_NON_OUTPUT = re.compile(
    r"\b(?:where|whose|having|matching|excluding|with|using|filtered"
    r"|(?:sort(?:ed|ing)?|order(?:ed|ing)?|group(?:ed|ing)?|rank(?:ed|ing)?)"
    r"\s+(?:(?:the\s+)?(?:rows|results)\s+)?by|filter (?:on|by))\b",
    re.I,
)
_EXCLUDED = re.compile(
    r"\b(?:instead of|rather than|without|except|excluding|not|no)\b", re.I
)
_RAW = r"(?:raw|stored|original|literal|untranslated)"
_LABEL_ALIAS = {"label", "description", "meaning"}


def _words(name: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", name.lower()))


def _display_parts(question: str):
    """Read output clauses, excluding filter conditions and negated display verbs."""
    question = re.sub(r"(?<=\w)\.(?=[A-Za-z_])", " ", question)
    question = re.sub(
        rf"\b(?:with|using)\s+(its|their)\s+((?:{_RAW}\s+)?codes?)\b",
        r"as \1 \2",
        question,
        flags=re.I,
    )
    for sentence in re.split(r"[;.!?\n]", question):
        cues = list(_OUTPUT.finditer(sentence))
        for index, cue in enumerate(cues):
            if re.search(r"\b(?:not|never|don't)\s*$", sentence[: cue.start()], re.I):
                continue
            end = cues[index + 1].start() if index + 1 < len(cues) else len(sentence)
            text = _NON_OUTPUT.split(sentence[cue.end() : end], maxsplit=1)[0]
            for part in re.split(r",|\band\b|\bthen\b", text, flags=re.I):
                yield _words(_EXCLUDED.split(part, maxsplit=1)[0])


def _requested_codes(
    question: str, columns: Sequence[str], sources: dict[int, tuple[Table, Column]]
) -> set[int]:
    """Bind explicit requests for stored values to named, projected coded fields."""
    names: dict[str, set[int]] = {}
    for index, (table, column) in sources.items():
        # These are the two abbreviations in the supported bank catalog.
        table_names = {
            table.name,
            {"trans": "transaction", "disp": "disposition"}.get(table.name, table.name),
        }
        descriptions = [column.name, columns[index], header(column.comment) or ""]
        descriptions.extend(name + " " + column.name for name in table_names)
        for description in descriptions:
            phrase = _words(description)
            if phrase:
                names.setdefault(phrase, set()).add(index)
    raw = set()
    for part in _display_parts(question):
        if not re.search(rf"\b(?:codes?|{_RAW})\b", part):
            continue
        matches = []
        for name, indices in names.items():
            field = re.escape(name)
            if re.search(
                rf"\b(?:{field}\s+(?:(?:as|in)\s+(?:a\s+|its\s+)?)?(?:{_RAW}\s+)?codes?"
                rf"|{_RAW}\s+{field}(?:\s+codes?)?(?!\s+(?:labels?|meanings?|descriptions?))"
                rf"|codes?\s+(?:for|of)\s+(?:the\s+)?{field})\b",
                part,
            ):
                matches.append((len(name.split()), indices))
        if matches:
            longest = max(n for n, _ in matches)
            targets = set.union(*(indices for n, indices in matches if n == longest))
        elif len(sources) == 1 and re.fullmatch(
            rf"(?:the |its |their )?(?:{_RAW} )?codes?", part
        ):
            targets = set(sources)
        else:
            continue
        if len(targets) > 1:
            # A simple name shared by different source fields cannot choose one.
            if len({(sources[i][0].name, sources[i][1].name) for i in targets}) != 1:
                continue
            targets = {
                i
                for i in targets
                if not (_LABEL_ALIAS & set(_words(columns[i]).split()))
            }
            marked = {
                i
                for i in targets
                if re.search(rf"\b(?:{_RAW}|code)\b", _words(columns[i]))
            }
            targets = marked or targets
        if len(targets) == 1:
            raw.update(targets)
    return raw


@dataclass(frozen=True)
class Display:
    """How to show one database's results. Empty means show them as is."""

    # Column name -> code -> meaning.
    values_by_column: dict[str, dict[str, str]] = field(default_factory=dict)
    # Codes with one meaning wherever they appear, for columns the query
    # renamed (SELECT type AS kind). One-letter codes such as loan
    # status B are too ambiguous to apply outside their own column.
    values_anywhere: dict[str, str] = field(default_factory=dict)
    # Column name -> header, e.g. a11 -> "Average salary".
    column_labels: dict[str, str] = field(default_factory=dict)
    # ISO code for money columns; None keeps the frontend's default.
    currency: str | None = None
    # Only schema-derived displays resolve returned fields to authorized source
    # columns. Explicitly supplied display maps retain their existing contract.
    schema: Schema | None = field(default=None, repr=False, compare=False)

    def value(self, column: str, value: Any) -> Any:
        """One cell as the user should see it."""
        if not isinstance(value, str):
            return value
        labels = self.values_by_column.get(column.lower(), {})
        if value in labels:
            return labels[value]
        return self.values_anywhere.get(value, value)

    def rows(
        self,
        columns: Sequence[str],
        rows: Sequence[Sequence[Any]],
        *,
        sql: str | None = None,
        question: str = "",
    ) -> list[tuple[Any, ...]]:
        if self.schema is not None and sql is not None:
            sources = {}
            mappings = {}
            for index, origin in enumerate(
                projected_columns(sql, len(columns), self.schema)
            ):
                if origin is not None:
                    labels = code_meanings(origin[1].comment)
                    if labels:
                        sources[index] = origin
                        mappings[index] = labels
            for index in _requested_codes(question, columns, sources):
                del mappings[index]
            return [
                tuple(
                    (
                        mappings[i].get(value, value)
                        if i in mappings and isinstance(value, str)
                        else value
                    )
                    for i, value in enumerate(row)
                )
                for row in rows
            ]
        return [tuple(self.value(c, v) for c, v in zip(columns, row)) for row in rows]


def _sentence(text: str) -> str:
    text = text.strip().rstrip(".;").strip()
    return text[:1].upper() + text[1:]


def code_meanings(comment: str) -> dict[str, str]:
    """The CODE = meaning pairs in one comment; lower-case keys such as
    "empty = not given" are descriptions, not codes, and are skipped."""
    meanings = {}
    for piece in _PAIR_SPLIT.split(comment):
        code, sep, meaning = piece.partition(" = ")
        if sep and _CODE.match(code.strip()):
            meanings[code.strip()] = _sentence(meaning)
    return meanings


def header(comment: str) -> str | None:
    """A short column header from a comment, or None if it is not one.

    "Average salary." -> "Average salary"; "Purpose: POJISTNE = ..." ->
    "Purpose"; a bare list of codes has no header.
    """
    if ":" in comment:
        comment = comment.split(":", 1)[0]
    elif " = " in comment:
        return None
    text = _sentence(comment)
    return text if text and len(text) <= MAX_LABEL_LENGTH else None


def display_for(schema: Schema) -> Display:
    """The display rules implied by the schema's comments."""
    by_column: dict[str, dict[str, str]] = {}
    meanings_of: dict[str, set[str]] = {}
    headers: dict[str, set[str | None]] = {}
    currencies: set[str] = set()

    for table in schema.tables.values():
        currencies.update(_CURRENCY.findall(table.comment))
        for column in table.columns:
            name = column.name.lower()
            meanings = code_meanings(column.comment)
            if meanings:
                by_column.setdefault(name, {}).update(meanings)
                for code, meaning in meanings.items():
                    meanings_of.setdefault(code, set()).add(meaning)
            headers.setdefault(name, set()).add(
                header(column.comment) if column.comment else None
            )

    return Display(
        schema=schema if by_column else None,
        values_by_column=by_column,
        values_anywhere={
            code: next(iter(found))
            for code, found in meanings_of.items()
            if len(found) == 1 and len(code) > 1
        },
        # Only when every column of that name agrees, so a date column
        # is not labelled with the one table's comment that has one.
        column_labels={
            name: next(iter(found))
            for name, found in headers.items()
            if len(found) == 1 and None not in found
        },
        currency=next(iter(currencies)) if len(currencies) == 1 else None,
    )
