"""Decide how many rows a question asks for, before the model writes SQL.

Left alone, the model answered "what are the least popular movies" with
one row, and "the least popular movie" with one arbitrary film out of
several tied for last place. Reading the question here, with plain rules
instead of the model, turns that into one explicit line in the prompt:

    "top 5", "which two customers"   -> exactly that many rows
    "least popular movies"           -> the top 10 (DEFAULT_LIST_ROWS)
    "the least popular movie", "who" -> first place plus every tie
    "top 3 films in each category"   -> the same rule within each group
    "lowest to highest"              -> ordering alone does not limit rows
    "shortest and longest lengths"   -> both endpoints of the measure
    "all", "every"                   -> no limit (execute.py still caps)

Questions with no ranking word ("films longer than 3 hours") get no
instruction; they already return every match.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Rows for a plural ranking question that gives no number.
DEFAULT_LIST_ROWS = 10

# The most rows a question may ask for; execute.py caps results at 1,000.
MAX_REQUESTED_ROWS = 1000

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "fifteen": 15,
    "twenty": 20,
    "twenty-five": 25,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "hundred": 100,
    "dozen": 12,
}
_NUMBER = r"(\d{1,4}|" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) + r")"

# Words that rank results. Comparatives ("more than 30") are filters, not
# rankings, so "more", "less" and "fewer" are deliberately absent.
_RANKING = (
    r"most|least|top|best|worst|highest|lowest|largest|smallest|biggest|"
    r"cheapest|priciest|longest|shortest|newest|oldest|latest|earliest|"
    r"fewest|greatest|bottom|\w+iest"
)
_RANKING_WORD = re.compile(rf"\b({_RANKING})\b")

# Opposite ends of the same measure can describe a sort direction or two
# requested values. Neither phrase by itself asks for the first ten rows.
_EXTREME_PAIRS = (
    ("lowest", "highest"),
    ("smallest", "largest"),
    ("shortest", "longest"),
    ("earliest", "latest"),
    ("oldest", "newest"),
    ("cheapest", "priciest"),
    ("minimum", "maximum"),
    ("least", "most"),
    ("worst", "best"),
)


def _opposites(joiner: str) -> str:
    return "|".join(
        first + joiner + second
        for low, high in _EXTREME_PAIRS
        for first, second in ((low, high), (high, low))
    )


_BOTH_EXTREMES = re.compile(r"\b(?:" + _opposites(r"\s+and\s+(?:the\s+)?") + r")\b")
_EXTREME_WORD = "|".join(word for pair in _EXTREME_PAIRS for word in pair)
# Match a short local phrase such as "lowest average speed first". Keep
# punctuation, conjunctions and independent selection clauses as boundaries.
_ORDER_DIRECTION = re.compile(
    r"\b(?:"
    + _opposites(r"\s+to\s+(?:the\s+)?")
    + rf"|(?:{_EXTREME_WORD})(?:\s+(?!(?:and|or|then|for|per|each|every|top|bottom|first)\b)[a-z]+){{0,3}}\s+first"
    + r"|(?:ascending|descending)\s+order)\b"
)

_COUNT_PATTERNS = [
    re.compile(rf"\b(?:top|first|last|bottom)\s+{_NUMBER}\b"),
    re.compile(rf"\b{_NUMBER}\s+(?:{_RANKING})\b"),
    re.compile(rf"\b(?:which|what)\s+{_NUMBER}\b"),
    re.compile(
        rf"^(?:please\s+)?(?:show|list|give|find|name|get|display|return)"
        rf"(?:\s+me)?(?:\s+the)?\s+{_NUMBER}\b"
    ),
]
_ALL = re.compile(r"\b(?:all|every)\b")
# "list customers by total spend", "show films ranked by rentals": a ranked
# list without a ranking word. The measure must follow "by", so a grouping
# like "rentals by store" is not mistaken for a ranking.
_RANKED_BY = re.compile(
    r"^(?:please\s+)?(?:list|show|give|rank|sort|order|display)\b.*?"
    r"\b(?:ranked\s+|sorted\s+|ordered\s+)?by\s+(?:the\s+)?(?:\w+\s+)?"
    r"(?:total|number|count|amount|average|sum|spend|spending|spent|revenue|"
    r"sales|payments?|rentals?|balance|salary|value)\b"
)
# "for each store", "per category", "in every country": rank within groups.
_PER_GROUP = re.compile(r"\b(?:each|per|(?:for|in)\s+every)\s+\w")
_TERMINAL_GROUP = re.compile(r"\b(?:in|from|for)\s+each\s*$")
_DISPLAY_VERB = r"(?:show|display|include|give|provide|report|return|list)"
_CLAUSE_BREAK = re.compile(
    rf"[.,;:!?]|\b(?:and|then|but)\s+(?=(?:also\s+)?{_DISPLAY_VERB}\b)"
    r"|\bwith\s+(?=(?:their|its)\b)"
)
# A second clause may ask for a field for every displayed row. Match only
# that projection; "for each of the regions" still names a partition.
_ROW_DETAIL = re.compile(
    r"(?:\band\s+|[.,;:!?]\s*)(?:also\s+)?"
    rf"{_DISPLAY_VERB}\s+"
    rf"(?:(?!(?:{_RANKING}|first|last|{_NUMBER})\b)[\w'-]+\s+){{1,6}}"
    r"for\s+each\s+of\s+them\b"
)
_RANK_COMMAND = re.compile(r"^(?:please\s+)?rank\b")
_PLURAL_VERB = re.compile(
    r"\b(?:what|which|who)\b(?:\s+\w+){0,4}?\s+(?:are|were|have)\b"
)
_SINGULAR_VERB = re.compile(
    r"\b(?:what|which|who)\b(?:\s+\w+){0,4}?\s+(?:is|was|has)\b"
)
_WHO = re.compile(r"^\s*who\b")
# The thing being ranked in "which customers spent the most money": the
# noun after which/what, not "money" after "most", which is the measure.
_SUBJECT = re.compile(r"\b(?:which|what)\s+(\w+)")

_IRREGULAR_PLURALS = {"people", "children", "men", "women", "data"}
# Words ending in "s" that are not plural nouns.
_NOT_PLURAL = {
    "is",
    "was",
    "has",
    "does",
    "this",
    "its",
    "his",
    "hers",
    "ours",
    "yours",
    "theirs",
    "less",
    "across",
    "plus",
    "always",
    "perhaps",
    "whose",
    "news",
    "series",
    "status",
    "address",
    "class",
    "business",
    "minus",
    "versus",
    "thus",
    "us",
    "as",
}


@dataclass(frozen=True)
class AnswerSize:
    """How many rows the question wants.

    kind is "count" (a number was given), "list" (plural, no number: the
    default applies), "single" (first place and its ties), "per_group"
    (the same within each group; rows is 1 for first place and ties), "all",
    "extremes" (both ends of a measure), or "open" (leave the query alone).
    """

    kind: str
    rows: int | None = None

    @property
    def instruction(self) -> str | None:
        """The line added to the prompt, or None for "open"."""
        if self.kind == "count":
            return (
                f"Answer size: return exactly {self.rows} rows. If the question "
                "ranks by a value, order by it and include it as a column, then "
                f"add LIMIT {self.rows}."
            )
        if self.kind == "list":
            return (
                "Answer size: the question asks for several results without a "
                f"number. Return the top {self.rows}: order by the value the "
                "question ranks by, from highest to lowest (lowest first only "
                "when it asks for the least, fewest, cheapest or lowest), "
                f"include that value as a column, and add LIMIT {self.rows}. "
                "Never answer with a single row."
            )
        if self.kind == "single":
            return (
                "Answer size: the question asks for the single top result. If it "
                "asks for the value itself (the highest price, the smallest "
                "amount), return that value with MAX or MIN. If it asks which "
                "rows reach it (which film, who), several may tie for first "
                "place, so return every tied row: rank with RANK() OVER (ORDER BY "
                "the value) in a WITH clause or subquery, keep rank 1, and "
                "include the value as a column. Do not use LIMIT 1."
            )
        if self.kind == "per_group":
            keep = (
                "rank 1 (every row tied for first)"
                if self.rows == 1
                else f"ranks 1 to {self.rows}"
            )
            return (
                "Answer size: the question ranks within each group. Use RANK() "
                "OVER (PARTITION BY the group ORDER BY the value the question "
                f"ranks by) in a WITH clause or subquery, keep {keep} in every "
                "group, and include the group and the value as columns."
            )
        if self.kind == "all":
            return "Answer size: the question asks for all matching rows; do not add a LIMIT."
        if self.kind == "extremes":
            return (
                "Answer size: return both ends of the requested measure using MIN and MAX. "
                "Compute them for each requested group if the question groups the data. "
                "If it asks which records attain either end, include all records tied there."
            )
        return None


def _number(text: str) -> int:
    return int(text) if text.isdigit() else _NUMBER_WORDS[text]


def _is_plural(word: str) -> bool:
    if word in _IRREGULAR_PLURALS:
        return True
    if word in _NOT_PLURAL or len(word) < 4 or not word.endswith("s"):
        return False
    return not word.endswith(("ss", "us", "is", "ous"))


def _noun_after_ranking(words: list[str]) -> str | None:
    """The first noun-like word within three words after the ranking word,
    skipping the adjectives in "least popular", "most rented"."""
    for word in words[:3]:
        if word in {"the", "a", "an", "of", "in", "by", "for"}:
            break
        if _is_plural(word):
            return word
        if (
            not word.endswith(("ed", "ar", "ive", "ful", "ing", "ent"))
            and len(word) > 3
        ):
            return word
    return None


def _requested_count(text: str) -> int | None:
    for pattern in _COUNT_PATTERNS:
        match = pattern.search(text)
        if match:
            rows = _number(match.group(1))
            if 1 <= rows <= MAX_REQUESTED_ROWS:
                return rows
    return None


def _within_groups(text: str, count: int | None) -> bool:
    scoped = _ROW_DETAIL.sub(" ", text)
    if _PER_GROUP.search(scoped):
        return True
    # A terminal "in/from/for each" can refer back to named groups. It
    # partitions the selection only when attached to the clause that supplied
    # its count or ranking. A later clause may ask for another displayed value.
    for clause in _CLAUSE_BREAK.split(scoped):
        selects_rows = (
            _requested_count(clause.strip()) == count
            if count is not None
            else _RANKING_WORD.search(clause) is not None
        )
        if selects_rows:
            return _TERMINAL_GROUP.search(clause) is not None
    return False


def _wants_one(text: str, ranking: re.Match[str]) -> bool:
    """True for singular wording ("the least popular movie", "who"),
    False for plural ("the least popular movies")."""
    # The verb settles it: "what is the most..." vs "what are the most...".
    if _PLURAL_VERB.search(text):
        return False
    if _SINGULAR_VERB.search(text):
        return True
    subject = _SUBJECT.search(text)
    if (
        subject
        and subject.start(1) != ranking.start()
        and subject.group(1)
        not in {
            "of",
            "the",
            "a",
            "an",
            "do",
            "does",
            "did",
        }
    ):
        return not _is_plural(subject.group(1))
    # Then the noun the ranking word describes: "most rented films".
    noun = _noun_after_ranking(re.findall(r"\w+", text[ranking.end() :]))
    if noun is not None:
        return not _is_plural(noun)
    # "Who spent the most?" asks for one person; "which customers spent
    # the most?" names a plural noun elsewhere in the question.
    if _WHO.search(text):
        return True
    return not any(_is_plural(word) for word in re.findall(r"\w+", text))


def answer_size(question: str) -> AnswerSize:
    """Read the question's wording; see the module docstring for the rules."""
    original = question.lower()
    # Work before stripping punctuation so "for each. Show..." cannot acquire
    # a group from the next sentence. Read explicit counts independently.
    count = _requested_count(" ".join(re.sub(r"[^\w\s'-]", " ", original).split()))
    text, extremes = _BOTH_EXTREMES.subn(" ", original)
    text, ordered = _ORDER_DIRECTION.subn(" ", text)
    text = " ".join(re.sub(r"[^\w\s'-]", " ", text).split())
    # "at least once", "at most 3 days" are filters, not rankings.
    text = re.sub(r"\bat (?:least|most)\b", "at", text)
    ranking = _RANKING_WORD.search(text)

    if (count or ranking) and _within_groups(original, count):
        if count:
            return AnswerSize("per_group", count)
        return AnswerSize(
            "per_group", 1 if _wants_one(text, ranking) else DEFAULT_LIST_ROWS
        )
    if count:
        return AnswerSize("count", count)
    if extremes and ranking is None:
        return AnswerSize("extremes")
    if _ALL.search(text):
        return AnswerSize("all")
    if ranking is None:
        if ordered:
            if _RANK_COMMAND.search(text):
                return AnswerSize("list", DEFAULT_LIST_ROWS)
            return AnswerSize("all")
        if _RANKED_BY.search(text):
            return AnswerSize("list", DEFAULT_LIST_ROWS)
        return AnswerSize("open")
    if _wants_one(text, ranking):
        return AnswerSize("single")
    return AnswerSize("list", DEFAULT_LIST_ROWS)
