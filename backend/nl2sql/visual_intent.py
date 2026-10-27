"""Decide whether a submitted task asks for a visual, without another model call."""

import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal

Intent = Literal["text", "explicit", "followup"]
_VISUAL = re.compile(
    r"\b(?:charts?|plots?|graphs?|visuali[sz](?:e|ation|ations))\b", re.I
)
_NEGATED = re.compile(
    r"\b(?:no|without|don't|do not|not)\s+(?:(?:want|need)\s+(?:to\s+)?)?(?:(?:show|draw|create|render|display|make|include|use|see)\s+)?(?:(?:me|us)\s+)?(?:(?:a|an|any|the)\s+)?(?:charts?|plots?|graphs?|visuali[sz](?:e|ations?))\b",
    re.I,
)
_POLITE = re.compile(
    r"^(?:(?:please|kindly)\s+|(?:can|could|would|will)\s+you\s+)", re.I
)
_EXPLAIN = re.compile(
    r"^(?:(?:and|also|now)\s+)?(?:explain|describe|summarize|why|define|what (?:does|is|are)|tell me about)\b",
    re.I,
)
_FOLLOWUP = re.compile(
    r"^(?:and|also|now|instead|only|same|filter|group|change|switch|use|for|by|what about)\b",
    re.I,
)
_MODIFIER = re.compile(
    r"\b(?:by|per|group|filter|only|last|next|year|month|week|day|quarter|region|categor(?:y|ies)|country|amount|revenue|count|top|bottom|same|instead|compare)\b",
    re.I,
)


def _task(text: str) -> str:
    """Strip only bounded leading courtesies before classifying the task."""
    text = text.strip()
    for _ in range(3):
        text = _POLITE.sub("", text, count=1)
    return text


def intent_for(question: str, context: Sequence[Mapping[str, Any]] = ()) -> Intent:
    """Only a narrow data follow-up inherits the latest uninterrupted visual task.

    A mention in an explanation is not a new chart request. The UI separately
    remembers dismissal: a follow-up must never reopen a user-closed pane.
    """

    def explicit(text: str) -> bool:
        text = _task(text)
        return bool(
            _VISUAL.search(text)
            and not _NEGATED.search(text)
            and not _EXPLAIN.search(text)
        )

    def follows(text: str) -> bool:
        text = _task(text)
        return bool(
            _FOLLOWUP.search(text)
            and _MODIFIER.search(text)
            and not _EXPLAIN.search(text)
            and not _NEGATED.search(text)
        )

    if explicit(question):
        return "explicit"
    visual = False
    for record in context[-8:]:
        text = record.get("question", "")
        if isinstance(text, str):
            visual = explicit(text) or (visual and follows(text))
    return "followup" if visual and follows(question) else "text"
