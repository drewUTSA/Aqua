"""Three catalog queries, zero row sampling, and explicit reviewed dataset scope."""

import psycopg
from psycopg import sql

from nl2sql.errors import ContextDenied
from nl2sql.metadata_policy import (
    BANK_TABLES,
    PAGILA_TABLES,
    COMMENTS,
    VALUES,
    ENUMS,
    DOMAINS,
)
from nl2sql.schema import Column, Schema, Table
from nl2sql.validate import HIDDEN_COLUMNS

TABLES_SQL = """
SELECT c.oid, c.relname
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r','p') AND NOT c.relispartition
  AND has_schema_privilege(n.oid, 'USAGE')
  AND has_any_column_privilege(c.oid, 'SELECT')
ORDER BY c.relname
"""
COLUMNS_SQL = """
SELECT a.attrelid, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull
FROM pg_attribute a
WHERE a.attrelid = ANY(%s) AND a.attnum > 0 AND NOT a.attisdropped
  AND has_column_privilege(a.attrelid, a.attnum, 'SELECT')
ORDER BY a.attrelid, a.attnum
"""
CONSTRAINTS_SQL = """
SELECT con.conrelid, con.contype,
 ARRAY(SELECT a.attname FROM unnest(con.conkey) WITH ORDINALITY k(num,pos)
       JOIN pg_attribute a ON a.attrelid=con.conrelid AND a.attnum=k.num ORDER BY k.pos),
 ref.relname, n.nspname,
 ARRAY(SELECT a.attname FROM unnest(con.confkey) WITH ORDINALITY k(num,pos)
       JOIN pg_attribute a ON a.attrelid=con.confrelid AND a.attnum=k.num ORDER BY k.pos)
FROM pg_constraint con
LEFT JOIN pg_class ref ON ref.oid=con.confrelid
LEFT JOIN pg_namespace n ON n.oid=ref.relnamespace
WHERE con.conrelid = ANY(%s) AND con.contype IN ('p','f')
ORDER BY con.conrelid, con.contype DESC, con.conname
"""


def _ident(name: str) -> str:
    """Identifiers are data; PostgreSQL's quoting rules also handle unusual names."""
    return sql.Identifier(name).as_string()


def _names(names: list[str]) -> str:
    # Catalog identifiers in supported datasets are lowercase conventional names.
    # Always quote SQL-sensitive names; prompt consistency does not grant access.
    return ", ".join(_ident(n) for n in names)


def load(conn: psycopg.Connection) -> Schema:
    """Discover the supported single dataset, failing closed on ambiguous scope."""
    observed = conn.execute(TABLES_SQL).fetchall()
    present = {name for _, name in observed}
    candidates = [
        tables for tables in (BANK_TABLES, PAGILA_TABLES) if tables <= present
    ]
    if len(candidates) != 1:
        raise ContextDenied("Dataset metadata does not match one reviewed manifest.")
    allowed = candidates[0]
    names = {oid: name for oid, name in observed if name in allowed}
    columns: dict[str, list[Column]] = {name: [] for name in allowed}
    for oid, name, type_name, required in conn.execute(COLUMNS_SQL, (list(names),)):
        table = names[oid]
        if (table, name) not in HIDDEN_COLUMNS:
            columns[table].append(
                Column(
                    name,
                    type_name,
                    required,
                    VALUES.get((table, name), ()),
                    COMMENTS.get(table + "." + name, ""),
                )
            )
    visible = {table: {c.name for c in cols} for table, cols in columns.items()}
    constraints: dict[str, list[str]] = {name: [] for name in allowed}
    references: dict[str, set[str]] = {name: set() for name in allowed}
    for oid, kind, keys, target, namespace, targets in conn.execute(
        CONSTRAINTS_SQL, (list(names),)
    ):
        table = names[oid]
        if not set(keys) <= visible[table]:
            continue
        if kind == "p":
            constraints[table].append(f"PRIMARY KEY ({_names(keys)})")
        elif (
            namespace == "public"
            and target in allowed
            and set(targets) <= visible[target]
        ):
            references[table].add(target)
            constraints[table].append(
                f"FOREIGN KEY ({_names(keys)}) REFERENCES {_ident(target)}({_names(targets)})"
            )
    tables = {
        name: Table(
            name,
            tuple(columns[name]),
            tuple(constraints[name]),
            frozenset(references[name]),
            COMMENTS.get(name, ""),
            '"order"' if name == "order" else name,
        )
        for name in sorted(allowed)
    }
    return Schema(
        tables,
        dict(ENUMS) if allowed == PAGILA_TABLES else {},
        dict(DOMAINS) if allowed == PAGILA_TABLES else {},
    )
