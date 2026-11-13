"""Bounded, request-local BM25/RRF over approved identifiers only."""

from collections import Counter
from itertools import islice
import math
import re

from nl2sql.errors import ContextDenied

MAX_TABLES = 2048
MAX_COLUMNS = 256
MAX_TERMS = 512
MAX_QUERY_TERMS = 32
RRF_K = 60
STOP = frozenset(
    "a an and are as at be by can each for from give has have how i id in into is list many me of on or please select show sql table tables tell that the these this those to what which with".split()
)


def tokens(text: str) -> list[str]:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text[:256])
    result = []
    for word in re.findall(r"[a-z][a-z0-9]*", text.lower()):
        if word in STOP:
            continue
        result.append(word)
        if len(word) > 4 and word.endswith("s") and not word.endswith(("ss", "us")):
            result.append(word[:-1])
        if len(result) >= MAX_QUERY_TERMS:
            break
    return result[:MAX_QUERY_TERMS]


def lexical(schema, question: str, limit: int = 4) -> list[str]:
    """Rank visible table/column names; comments, values and rows are excluded."""
    query = set(tokens(question))
    if not query:
        return []
    docs = {}
    for name in sorted(islice(schema.tables, MAX_TABLES)):
        table = schema.tables[name]
        words = tokens(name) * 3
        for column in islice(table.columns, MAX_COLUMNS):
            words.extend(tokens(column.name))
            if len(words) >= MAX_TERMS:
                break
        docs[name] = Counter(words[:MAX_TERMS])
    if not docs:
        return []
    lengths = {name: sum(count.values()) for name, count in docs.items()}
    average = sum(lengths.values()) / len(docs) or 1
    frequency = {term: sum(term in count for count in docs.values()) for term in query}
    scores = {}
    for name, count in docs.items():
        score = 0.0
        for term in query:
            tf = count[term]
            if tf:
                idf = math.log1p(
                    (len(docs) - frequency[term] + 0.5) / (frequency[term] + 0.5)
                )
                score += (
                    idf
                    * tf
                    * 2.2
                    / (tf + 1.2 * (0.25 + 0.75 * lengths[name] / average))
                )
        if score > 0:
            scores[name] = score
    return sorted(scores, key=lambda name: (-scores[name], name))[:limit]


def hybrid_tables(schema, nearest, question: str, limit: int = 4) -> list[str]:
    """Fuse ranks, preserving the original fail-closed index boundary."""
    if not 1 <= limit <= 8:
        raise ValueError("hybrid_limit_invalid")
    vector = list(dict.fromkeys(nearest))
    if not set(vector) <= schema.allowed_tables:
        # Never hide an unauthorized vector hit by replacing it with safe hits.
        raise ContextDenied("Retrieval index contains an unauthorized relation.")
    if not vector:
        return []  # Preserve empty-index availability/fallback behavior.
    keyword = lexical(schema, question, limit)
    if not keyword:
        return vector[:limit]
    scores = {}
    for ranking in (vector[:limit], keyword):
        for rank, name in enumerate(ranking, 1):
            scores[name] = scores.get(name, 0.0) + 1.0 / (RRF_K + rank)
    original = {name: rank for rank, name in enumerate(vector)}
    return sorted(
        scores, key=lambda name: (-scores[name], original.get(name, len(vector)), name)
    )[:limit]
