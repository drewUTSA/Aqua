"""Explicit grouped rankings. Only a complete, source-qualified command can execute."""

from nl2sql.config import Settings
from nl2sql.control import stage
from nl2sql.errors import diagnostic
from nl2sql.execute import DEFAULT_MAX_ROWS, QueryError, execute
from nl2sql.group_rank_language import parse
from nl2sql.grouped_rank import compile_grouped_rank
from nl2sql.pipeline import Answer
from nl2sql.schema import Schema
from nl2sql.validate import UnsafeQueryError, validate_sql

PREFIX = "Rank groups: "
ERROR = "ranking_request_invalid"


def is_ranking_request(question: str) -> bool:
    # Submission normalizes trailing whitespace, including a marker with no body.
    return question.startswith(PREFIX) or question == PREFIX.rstrip()


def feedback(question: str, code: str = ERROR) -> Answer:
    return Answer(
        question=question,
        sql="",
        attempts=0,
        error=diagnostic(code).message,
        error_code=code,
    )


def _canonical(sentence: str) -> bool:
    intent = parse(sentence)
    if not intent or not intent.source:
        return False
    if intent.measure != "row count" and not intent.measure.startswith("total "):
        return False
    heading = f"from {intent.source}, "
    order = "top" if intent.direction == "DESC" else "bottom"
    by = f"{order} {intent.rows} {intent.group} by {intent.measure}"
    if intent.policy == "cutoff":
        body = f"show the {by}, including ties."
    elif intent.policy == "exact":
        body = f"show exactly the {by}."
    elif intent.policy == "levels":
        level = "highest" if intent.direction == "DESC" else "lowest"
        body = (
            f"which {intent.group} have one of the {level} {intent.rows} "
            f"distinct {intent.measure} values?"
        )
    else:
        return False
    return " ".join(sentence.lower().replace("_", " ").split()) == heading + body


def answer_ranking(
    question: str, settings: Settings, schema: Schema, max_rows: int = DEFAULT_MAX_ROWS
) -> Answer:
    sentence = question.removeprefix(PREFIX)
    if not is_ranking_request(question) or not _canonical(sentence):
        return feedback(question)
    # The catalog is read with the current dataset role. The fully qualified
    # source is explicit, so this route needs neither examples nor an embedding.
    stage("validating")
    ranking = compile_grouped_rank(sentence, schema, tuple(schema.tables))
    if ranking is None:
        return feedback(question)
    try:
        query = validate_sql(ranking.sql, allowed_tables=schema.allowed_tables)
        stage("executing")
        result = execute(query, settings, max_rows=max_rows)
    except UnsafeQueryError:
        return feedback(question, "rejected")
    except QueryError as exc:
        return feedback(question, exc.code)
    return Answer(
        question=question,
        sql=result.sql,
        columns=result.columns,
        rows=result.rows,
        truncated=result.truncated,
        model="Aqua grouped ranking",
        attempts=0,
        size=ranking.size,
    )
