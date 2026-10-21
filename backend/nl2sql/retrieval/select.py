"""Pick the tables and worked examples nearest to a question.

Runs at question time as the read-only role: one embedding call for the
question, then two nearest-neighbour lookups in the retrieval schema.
The result is a pipeline.Context, so the pipeline treats retrieved and
full-schema prompts the same way.

Which tables go in the prompt:
- the TOP_TABLES descriptions nearest the question,
- every table the retrieved examples used, since those joins worked,
- any table that links two chosen ones (film_category between film and
  category), so the model never has to join through a table it cannot see.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import psycopg

from nl2sql.errors import ContextDenied, RetrievalUnavailable
from nl2sql.validate import UnsafeQueryError, validate_sql

from nl2sql.config import Settings
from nl2sql.db import DatabaseError, connect
from nl2sql.generate import Example
from nl2sql.pipeline import Context
from nl2sql.retrieval.embed import EmbeddingError, embed_query, to_pgvector
from nl2sql.schema import Schema

TOP_TABLES = 4
TOP_EXAMPLES = 3

_TABLES_SQL = """
SELECT table_name
FROM retrieval.schema_doc
WHERE embed_model = %s
ORDER BY embedding <=> %s::vector
LIMIT %s
"""

# Only examples a person has checked; see db/04_retrieval.sql.
_EXAMPLES_SQL = """
SELECT question, sql, tables
FROM retrieval.example_query
WHERE verified AND embed_model = %s
ORDER BY embedding <=> %s::vector
LIMIT %s
"""


class RetrievalError(RetrievalUnavailable):
    """Raised when there is nothing to retrieve, e.g. the index is empty."""


def choose_tables(
    schema: Schema, nearest: Iterable[str], example_tables: Iterable[str]
) -> set[str]:
    """The nearest tables, the examples' tables, and the links between them."""
    chosen = {
        t.lower() for t in [*nearest, *example_tables] if t.lower() in schema.tables
    }
    bridges = {
        name
        for name in schema.tables
        if name not in chosen and len((schema.related([name]) - {name}) & chosen) >= 2
    }
    return chosen | bridges


def assemble(
    schema: Schema,
    nearest: Sequence[str],
    examples: Sequence[tuple[str, str, Sequence[str]]],
) -> Context:
    """Build the Context from lookup results. Separate so it can be tested
    without a database or an embedding API."""
    if not nearest:
        raise RetrievalError(
            "The retrieval index is empty; run python -m nl2sql.retrieval.store."
        )
    if not set(nearest) <= schema.allowed_tables:
        raise ContextDenied("Retrieval index contains an unauthorized relation.")
    for _, sql, used in examples:
        if not set(used) <= schema.allowed_tables:
            raise ContextDenied("Retrieval example declares an unauthorized relation.")
        try:
            validate_sql(sql, allowed_tables=used)
        except UnsafeQueryError:
            raise ContextDenied(
                "Retrieval example SQL is outside its declared relations."
            ) from None
    tables = choose_tables(
        schema, nearest, [t for _, _, used in examples for t in used]
    )
    return Context(
        schema_text=schema.to_prompt(tables),
        examples=tuple(Example(question, sql) for question, sql, _ in examples),
        tables=tuple(sorted(tables)),
    )


class VectorRetriever:
    """The Retriever the app uses when RETRIEVAL is on."""

    def __init__(self, settings: Settings, embed_client: Any = None) -> None:
        self.settings = settings
        self.embed_client = embed_client

    def select(self, question: str, schema: Schema) -> Context:
        """Classify availability separately from authorization and index integrity."""
        try:
            return self._select(question, schema)
        except EmbeddingError as error:
            if error.transient:
                raise RetrievalUnavailable("Embedding service unavailable.") from None
            raise ContextDenied("Embedding service rejected context.") from None
        except psycopg.OperationalError as error:
            if error.sqlstate and error.sqlstate.startswith("28"):
                raise ContextDenied("Retrieval authorization failed.") from None
            raise RetrievalUnavailable("Retrieval connection unavailable.") from None
        except DatabaseError as error:
            cause = error.__cause__
            if isinstance(cause, psycopg.OperationalError) and not (
                cause.sqlstate or ""
            ).startswith("28"):
                raise RetrievalUnavailable(
                    "Retrieval connection unavailable."
                ) from None
            raise ContextDenied("Retrieval connection failed closed.") from None

    def _select(self, question: str, schema: Schema) -> Context:
        vector = to_pgvector(embed_query(question, self.settings, self.embed_client))
        model = self.settings.gemini_embed_model
        with connect(self.settings) as conn:
            nearest = [
                row[0] for row in conn.execute(_TABLES_SQL, (model, vector, TOP_TABLES))
            ]
            examples = conn.execute(
                _EXAMPLES_SQL, (model, vector, TOP_EXAMPLES)
            ).fetchall()
        return assemble(schema, nearest, examples)
