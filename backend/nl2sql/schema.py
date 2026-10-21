"""Read the database's tables, columns and keys into text for the prompt.

The model can only write correct SQL for tables it can see, so the
prompt carries the schema. Reading it from the live database (as the
read-only role) instead of a hand-kept file means the prompt can never
drift from what the database really has.

The same Schema object gives the validator its table allowlist, gives
retrieval one short description per table to embed, and lists the
tables joined to a given table so retrieval can bring them along.

Run `python -m nl2sql.schema` from backend/ to print the prompt text.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field

import psycopg

from nl2sql.config import Settings, load_settings
from nl2sql.db import DatabaseError, connect

# Columns the model is never shown; the validator also refuses them.
# staff.password is a credential hash, staff.picture is binary.
from nl2sql.validate import HIDDEN_COLUMNS as HIDDEN_COLUMNS


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    not_null: bool
    # Distinct values, only for short text columns (see MAX_LISTED_VALUES).
    values: tuple[str, ...] = ()
    # The column's database comment, e.g. what a code like PRIJEM means.
    comment: str = ""


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[Column, ...]
    # Constraint text as Postgres prints it, e.g. "PRIMARY KEY (film_id)".
    constraints: tuple[str, ...]
    # Tables this one has a foreign key to.
    references: frozenset[str]
    # The table's database comment.
    comment: str = ""
    # The name as SQL must write it: "order" is quoted, film is not.
    quoted_name: str = ""


@dataclass(frozen=True)
class Schema:
    """The visible part of the database, keyed by lowercase table name."""

    tables: dict[str, Table]
    # Enum type name -> its labels in order, e.g. mpaa_rating.
    enums: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # Domain name -> base type, e.g. year -> integer.
    domains: dict[str, str] = field(default_factory=dict)

    @property
    def allowed_tables(self) -> frozenset[str]:
        """Every table generated SQL may read."""
        return frozenset(self.tables)

    def related(self, names: Iterable[str]) -> set[str]:
        """The given tables plus every table joined to them in one step.

        Joins come from foreign keys, and from a column named like
        another table's key (payment.customer_id -> customer), because
        partitioned tables such as payment carry no foreign keys of
        their own in Pagila.
        """
        chosen = {n.lower() for n in names if n.lower() in self.tables}
        result = set(chosen)
        for name, table in self.tables.items():
            links = set(table.references) | {
                c.name[: -len("_id")]
                for c in table.columns
                if c.name.endswith("_id") and c.name[: -len("_id")] in self.tables
            }
            links.discard(name)
            if name in chosen:
                result |= links
            elif links & chosen:
                result.add(name)
        return result

    def to_prompt(self, names: Iterable[str] | None = None) -> str:
        """CREATE statements for the given tables (all when None).

        Types the tables use (enums, domains) come first, so the model
        knows rating is one of five values and release_year an integer.
        """
        picked = sorted(
            self.tables
            if names is None
            else {n.lower() for n in names} & set(self.tables)
        )
        used_types = {c.type for name in picked for c in self.tables[name].columns}
        parts = [
            f"CREATE TYPE {name} AS ENUM ({', '.join(_quote(v) for v in labels)});"
            for name, labels in sorted(self.enums.items())
            if name in used_types
        ]
        parts += [
            f"CREATE DOMAIN {name} AS {base};"
            for name, base in sorted(self.domains.items())
            if name in used_types
        ]
        parts += [_create_table(self.tables[name]) for name in picked]
        return "\n\n".join(parts)

    def describe(self, name: str) -> str:
        """One table as a short plain-text document, for embedding.

        Names are spelled out with spaces so a question like "which
        customers spent the most" lands near customer and payment.
        """
        table = self.tables[name.lower()]
        columns = ", ".join(c.name.replace("_", " ") for c in table.columns)
        text = (
            f"Table {table.name.replace('_', ' ')} ({table.name}). Columns: {columns}."
        )
        joined = sorted(self.related([table.name]) - {table.name})
        if table.comment:
            text += f" {table.comment}"
        if joined:
            text += f" Joins to: {', '.join(joined)}."
        listed = [c for c in table.columns if c.values]
        for column in listed:
            text += f" {column.name} values: {', '.join(column.values)}."
        return text


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _display_value(value: str) -> str:
    """A listed value as the prompt shows it.

    Padding is trimmed (Pagila's character(20) names), but a value that
    is only blanks is shown quoted, because ' ' and '' are different
    values and the model has to write the right one.
    """
    return _quote(value) if not value.strip() else value.strip()


def _one_line(text: str | None) -> str:
    """A database comment on one line; None (no comment) becomes ''."""
    return " ".join((text or "").split())


def _create_table(table: Table) -> str:
    lines = []
    for c in table.columns:
        line = f"  {c.name} {c.type}" + (" NOT NULL" if c.not_null else "")
        notes = c.comment
        if c.values:
            listed = ", ".join(c.values)
            notes = f"{notes} Values: {listed}" if notes else f"values: {listed}"
        if notes:
            line += f"  -- {notes}"
        lines.append(line)
    lines += [f"  {text}" for text in table.constraints]
    # Commas go between items, before any trailing "-- values" comment.
    body = []
    for i, line in enumerate(lines):
        last = i == len(lines) - 1
        head, sep, comment = line.partition("  -- ")
        body.append(head + ("" if last else ",") + (f"  -- {comment}" if sep else ""))
    head = f"-- {table.comment}\n" if table.comment else ""
    return (
        head
        + f"CREATE TABLE {table.quoted_name or table.name} (\n"
        + "\n".join(body)
        + "\n);"
    )


def load_schema(conn: psycopg.Connection) -> Schema:
    """Load only the reviewed dataset catalog and approved static metadata."""
    from nl2sql.schema_loader import load

    return load(conn)


_cache: dict[str, Schema] = {}
_cache_lock = threading.Lock()


def get_schema(settings: Settings) -> Schema:
    """The schema for settings.database_url, read once per process.

    Cached because it only changes when someone runs a db/ script, and
    reading it takes three bounded catalog queries. A failed read is not
    cached, so the next request tries again. Raises db.DatabaseError if
    the database cannot be reached.
    """
    with _cache_lock:
        cached = _cache.get(settings.database_url)
        if cached is not None:
            return cached
        try:
            with connect(settings) as conn:
                schema = load_schema(conn)
        except psycopg.Error:
            raise DatabaseError("Could not read the authorized schema.") from None
        _cache[settings.database_url] = schema
        return schema


def main() -> int:
    """Print the prompt text, as a quick check that introspection works."""
    try:
        schema = get_schema(load_settings())
    except DatabaseError as exc:
        print(exc)
        return 1
    print(schema.to_prompt())
    print(f"\n-- {len(schema.tables)} tables: {', '.join(sorted(schema.tables))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
