"""Answer a question end to end: build context, generate SQL, validate, run.

This is the one place the steps are put together, so the order and the
safety rule live here: SQL the validator rejects is never executed.

Problems with the question's SQL (rejected by the validator, or refused
by the database) come back inside the Answer as an error, so the user
can see the SQL and the reason. When the problem is one the model could
fix (a typo, a wrong column), it gets one more try with a fixed diagnostic.
Raw exception text never becomes a repair hint. Service failures (model or database
unreachable) raise LLMError or DatabaseError for the API to report as a
server error.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from nl2sql.answer_size import AnswerSize, answer_size
from nl2sql.config import Settings
from nl2sql.errors import ContextDenied, RetrievalUnavailable, diagnostic
from nl2sql.execute import DEFAULT_MAX_ROWS, QueryError, execute
from nl2sql.generate import Attempt, Example, generate_sql
from nl2sql.schema import Schema
from nl2sql.validate import UnsafeQueryError, validate_sql
from nl2sql.control import stage

log = logging.getLogger(__name__)

# One first try plus one correction. More rarely helps and doubles the
# wait each time with reasoning on.
MAX_ATTEMPTS = 2


@dataclass(frozen=True)
class Context:
    """What the model sees besides the question."""

    schema_text: str
    examples: tuple[Example, ...] = ()
    tables: tuple[str, ...] = ()


class Retriever(Protocol):
    """Anything that can pick the relevant context for a question."""

    def select(self, question: str, schema: Schema) -> Context: ...


@dataclass(frozen=True)
class Answer:
    """Everything the API needs to reply to one question.

    sql is the statement that ran (with its row limit), or the last one
    the model wrote if it was rejected. error_code is "rejected" when the
    validator refused the SQL and "query_failed" when the database did;
    both are None on success. attempts counts model calls (1 or 2).
    """

    question: str
    sql: str
    columns: list[str] = field(default_factory=list)
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    truncated: bool = False
    thinking: str = ""
    model: str = ""
    error: str | None = None
    error_code: str | None = None
    attempts: int = 1
    used_retrieval: bool = False
    # How many rows the question asked for (answer_size.py); the response
    # says so when the default list size or a tie decided the answer.
    size: AnswerSize = field(default_factory=lambda: AnswerSize("open"))


def full_context(schema: Schema) -> Context:
    """Every table, no examples: the baseline without retrieval."""
    return Context(schema_text=schema.to_prompt(), tables=tuple(sorted(schema.tables)))


def build_context(
    question: str, schema: Schema, retriever: Retriever | None
) -> tuple[Context, bool]:
    """Fallback is only for classified outages, within the same authorized schema."""
    if retriever is None:
        return full_context(schema), False
    try:
        context = retriever.select(question, schema)
    except RetrievalUnavailable:
        log.warning("retrieval_unavailable action=authorized_schema_fallback")
        return full_context(schema), False
    except Exception:
        # Unknown failures are not evidence of safe availability-only failure.
        # Do not log provider/DB exceptions, which can contain data or credentials.
        log.warning("retrieval_denied action=stop")
        raise ContextDenied("Authorized retrieval context is unavailable.") from None
    if not context.tables or not set(context.tables) <= schema.allowed_tables:
        raise ContextDenied("Retrieval selected an unauthorized relation.")
    if len(context.examples) > 3:
        raise ContextDenied("Retrieval exceeds the approved example budget.")
    for example in context.examples:
        if len(example.question) > 2000 or len(example.sql) > 32768:
            raise ContextDenied("Retrieval example exceeds the input budget.")
        try:
            validate_sql(example.sql, allowed_tables=context.tables)
        except UnsafeQueryError:
            raise ContextDenied(
                "Retrieval example violates the dataset policy."
            ) from None
    # Never trust schema text from an index or retriever. Render approved metadata.
    return (
        Context(schema.to_prompt(context.tables), context.examples, context.tables),
        True,
    )


def answer_question(
    question: str,
    settings: Settings,
    schema: Schema,
    retriever: Retriever | None = None,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> Answer:
    """Turn a question into rows, or into a clear reason it could not.

    Raises ValueError for an empty question, llm.LLMError if the model
    is unreachable and db.DatabaseError if the database is.
    """
    question = question.strip()
    if not question:
        raise ValueError("Question is empty.")

    stage("retrieval")
    context, used_retrieval = build_context(question, schema, retriever)
    size = answer_size(question) if settings.answer_size_rules else AnswerSize("open")
    previous: Attempt | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        stage("generating")
        generation = generate_sql(
            question,
            context.schema_text,
            settings,
            examples=context.examples,
            previous=previous,
            size=size.instruction,
        )
        base = {
            "question": question,
            "thinking": generation.thinking,
            "model": generation.model,
            "attempts": attempt,
            "used_retrieval": used_retrieval,
            "size": size,
        }
        try:
            stage("validating")
            query = validate_sql(generation.sql, allowed_tables=schema.allowed_tables)
            stage("executing")
            result = execute(query, settings, max_rows=max_rows)
        except UnsafeQueryError as exc:
            error, code, fixable = (
                diagnostic("rejected").message,
                "rejected",
                exc.fixable,
            )
            repair_code = "repair_query"
        except QueryError as exc:
            error, code = str(exc), "query_failed"
            fixable = exc.fixable
            repair_code = exc.code
        else:
            return Answer(
                sql=result.sql,
                columns=result.columns,
                rows=result.rows,
                truncated=result.truncated,
                **base,
            )

        log.warning(
            "query_denied category=%s repair=%s attempt=%d", code, repair_code, attempt
        )
        if not fixable or attempt == MAX_ATTEMPTS:
            return Answer(sql=generation.sql, error=error, error_code=code, **base)
        previous = Attempt(generation.sql, repair_code)

    raise AssertionError("unreachable: the loop always returns")
