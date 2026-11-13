"""Carry bounded owned follow-up meaning into the existing embedding call."""

import json
from collections.abc import Sequence

MAX_QUERY_BYTES = 12000
MAX_HISTORY_QUESTIONS = 2


def retrieval_query(question: str, context: Sequence[dict] = ()) -> str:
    """Use only questions from the job's already authorized frozen context.

    The caller supplies the current job's grant-fenced context, not arbitrary
    account history. SQL, rows, identifiers, receipts and other fields never
    enter the embedding input. No new provider call or persistent index is added.
    """
    if len(question.encode("utf-8")) > MAX_QUERY_BYTES:
        raise ValueError("retrieval_query_budget")
    previous: list[str] = []
    for item in reversed(context[-8:]):
        if type(item) is not dict:
            continue
        prior = item.get("question")
        if (
            not isinstance(prior, str)
            or not prior.strip()
            or len(prior) > 2000
            or prior == question
            or prior in previous
        ):
            continue
        candidate = [prior, *previous]
        raw = json.dumps(
            {"earlier_questions": candidate, "current_question": question},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(raw.encode("utf-8")) <= MAX_QUERY_BYTES:
            previous = candidate
        if len(previous) == MAX_HISTORY_QUESTIONS:
            break
    if not previous:
        return question
    return json.dumps(
        {"earlier_questions": previous, "current_question": question},
        ensure_ascii=False,
        separators=(",", ":"),
    )
