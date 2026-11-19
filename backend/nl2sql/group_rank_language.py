"""Consume a complete grouped-ranking question, keeping membership separate from display."""

from dataclasses import dataclass
import re
from typing import Literal

from nl2sql.answer_size import explicit_row_count

Policy = Literal["exact", "cutoff", "levels", "extremum"]


@dataclass(frozen=True)
class Ranking:
    group: str
    measure: str
    source: str | None
    direction: Literal["ASC", "DESC"]
    rows: int
    policy: Policy
    projection: str | None
    display: str | None
    tiebreak: str | None
    within_ties: bool


_VOCAB = r"[a-z0-9][a-z0-9 -]*?"
_VERB = r"(?:(?:please )?(?:show|list|give|return|display|find|name|rank)(?: me)? (?:the )?)?"
_DIRECTION = r"top|bottom|highest|lowest|largest|smallest|greatest|least|most|fewest|maximum|minimum"
_COUNT = r"[a-z]+(?:-[a-z]+)?|[0-9]+"
_TOP = re.compile(
    rf"{_VERB}(?P<hard>(?:exactly |only )(?:the )?)?(?P<direction>top|bottom) (?P<n>{_COUNT}) "
    rf"(?P<group>{_VOCAB}) (?:ranked |ordered |sorted )?by (?:the )?(?P<metric>{_VOCAB})"
)
_ORDERED_N = re.compile(
    rf"{_VERB}(?P<hard>(?:exactly |only )(?:the )?)?(?P<n>{_COUNT}) "
    rf"(?P<direction>highest|lowest|largest|smallest) (?P<group>{_VOCAB}) by (?:the )?(?P<metric>{_VOCAB})"
)
_BY_VALUE = re.compile(
    rf"(?:which |what |{_VERB})(?:all |every )?(?P<group>{_VOCAB}) "
    rf"(?:have|has|had|recorded|with|share|shares|tied for|are tied for|is tied for|were tied for) "
    rf"(?P<one_of>one of )?(?:the )?(?P<direction>{_DIRECTION}) "
    rf"(?:(?P<n>{_COUNT}) (?P<levels>distinct|different) )?(?P<metric>{_VOCAB})"
)
_EXACT = re.compile(
    rf"{_VERB}exactly (?P<n>{_COUNT}) (?P<group>{_VOCAB}) with (?:the )?"
    rf"(?P<direction>{_DIRECTION}) (?P<metric>{_VOCAB})"
)
_OUTPUT = r"show|return|display|output|list|give|provide"
_CLAUSE = re.compile(
    rf"(?:[.;?!] +|,? (?:and |then )?(?=(?:{_OUTPUT}|include|including|keep|retain|"
    r"with (?:all )?ties|break ties|breaking ties|sort by|order by|within ties by)\b))"
)
_TIES = re.compile(
    r"(?:include|including|keep|retain|with|show|return) (?:(?:all|any|the) )?(?:ties|tied groups|groups tied)"
    r"(?: (?:at (?:the )?cutoff|for (?:the )?last place))?"
)


def parse(question: str) -> Ranking | None:
    if len(question) > 640 or not question.isascii():
        return None
    text = " ".join(question.lower().replace("_", " ").split())
    text = re.sub(r"[?.!]$", "", text)
    if not re.fullmatch(r"[a-z0-9 ,;.?!-]+", text):
        return None
    source = None
    if prefix := re.fullmatch(rf"(?:from|using|in) (?:the )?({_VOCAB}), (.+)", text):
        source, text = prefix.groups()
    # A source-first GROUP BY explicitly supplies the population and group.
    # Reconstruct only the two recognized grammatical slots; every remaining
    # token goes through the same selection, projection and ordering parser.
    if grouped := re.fullmatch(
        rf"(?:please )?group (?:the )?({_VOCAB}) by (?:the )?({_VOCAB})(?:[.;,] | and )"
        rf"(?:then )?{_VERB}((?:exactly (?:the )?)?(?:top|bottom) (?:{_COUNT}))"
        rf"(?: groups)? by (.+)",
        text,
    ):
        fact, group, cutoff, rest = grouped.groups()
        if source and source != fact:
            return None
        source, text = fact, f"{cutoff} {group} by {rest}"
    text = re.sub(
        r"within (?:each tie|ties),? (?:sort|order) by ", "within ties by ", text
    )
    # A leading selection verb belongs to the main clause.
    split = _CLAUSE.split(text, maxsplit=8)
    head, *options = split
    if suffix := re.fullmatch(rf"(.+) (?:from|in|using) (?:the )?({_VOCAB})", head):
        head, end_source = suffix.groups()
        if source and source != end_source:
            return None
        source = end_source
    match = (
        _TOP.fullmatch(head)
        or _ORDERED_N.fullmatch(head)
        or _EXACT.fullmatch(head)
        or _BY_VALUE.fullmatch(head)
    )
    if not match:
        return None
    fields = match.groupdict()
    group, metric = fields["group"], fields["metric"]
    direction = (
        "ASC"
        if fields["direction"]
        in {"bottom", "least", "lowest", "smallest", "fewest", "minimum"}
        else "DESC"
    )
    n = fields.get("n")
    rows = explicit_row_count(n) if n else 1
    if (
        rows is None
        or (not n and fields["direction"] in {"top", "bottom"})
        or (fields.get("one_of") and not fields.get("levels"))
    ):
        return None
    policy: Policy = "exact" if n else "extremum"
    if fields.get("levels"):
        policy = "levels"
        metric = re.sub(r" (?:values|tiers|levels)$", "", metric)
    hard = match.re is _EXACT or bool(fields.get("hard"))
    if fields["direction"] in {"most", "fewest"}:
        # A source noun in this position counts its records. A bare amount,
        # duration or salary supplies no evidence for SUM.
        metric = "number of " + metric
    projection = display = tiebreak = None
    within = False
    for option in options:
        if _TIES.fullmatch(option):
            if hard or tiebreak:
                return None
            if policy == "exact":
                policy = "cutoff"
        elif item := re.fullmatch(r"(?:break|breaking) ties by (.+)", option):
            if tiebreak or policy != "exact":
                return None
            tiebreak = item[1]
        elif item := re.fullmatch(
            r"(?:(within ties by)|(?:sort|order)(?: (?:the )?(?:rows|results))? by) (.+)",
            option,
        ):
            if display:
                return None
            within, display = bool(item[1]), item[2]
        elif item := re.fullmatch(rf"(?:{_OUTPUT}) (?:only )?(.+)", option):
            if projection:
                return None
            projection = item[1].removesuffix(" only")
        else:
            return None
    return Ranking(
        group,
        metric,
        source,
        direction,
        rows,
        policy,
        projection,
        display,
        tiebreak,
        within,
    )
