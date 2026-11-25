"""Bounded non-executable hints preserve the existing saved-ranking review form.

Only the complete simple form formerly recognized in the browser is admitted.
The statement stays on the server; filtered, joined or ambiguous ranks have no
prefill. The employee must still choose a tie rule and explicitly send a draft.
"""

import re

IDENT = r'(?:"[a-z][a-z0-9_]{0,62}"|[a-z][a-z0-9_]{0,62})'
COLUMN = rf"{IDENT}(?:\s*\.\s*{IDENT})?"
AGGREGATE = rf"(?:COUNT\s*\(\s*\*\s*\)|SUM\s*\(\s*{COLUMN}\s*\))"
QUERY = re.compile(
    rf"^SELECT\s+(?P<key>{COLUMN})(?:\s+AS\s+(?P<keyLabel>{IDENT}))?\s*,\s*"
    rf"(?P<metric>{AGGREGATE})(?:\s+AS\s+(?P<scoreLabel>{IDENT}))?\s+"
    rf"FROM\s+(?P<relation>{COLUMN})(?:\s+(?:AS\s+)?(?P<alias>{IDENT}))?\s+"
    rf"GROUP\s+BY\s+(?P<group>{COLUMN}|1)\s+"
    rf"ORDER\s+BY\s+(?P<score>{AGGREGATE}|{IDENT}|2)(?:\s+(?P<direction>ASC|DESC))?\s+"
    r"(?:LIMIT\s+(?P<limit>[1-9][0-9]{0,2})|FETCH\s+(?:FIRST|NEXT)\s+"
    r"(?P<fetch>[1-9][0-9]{0,2})\s+ROWS?\s+(?:ONLY|WITH\s+TIES))\s*;?$",
    re.I,
)
SMALL = "one two three four five six seven eight nine ten".split()
NUMBER = rf"(?:[0-9]+|{'|'.join(SMALL)})"
CUTOFF = re.compile(
    rf"\b(top|bottom|highest|lowest)\s+({NUMBER})\b|\b({NUMBER})\s+(highest|lowest|largest|smallest|most|fewest)\b",
    re.I,
)
BEFORE = re.compile(
    r"(?:[\d.,/-]|\b(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|and|or|to)\s+|\d+\s+)$",
    re.I,
)
AFTER = re.compile(
    r"^(?:[.,]\d|\s*(?:[%/–-]|percent\b|per\s+cent\b|hundred\b|thousand\b|million\b|dozen\b|and\s+a\s+half\b|(?:to|or)\s+(?:\d|one\b|two\b|three\b|four\b|five\b|six\b|seven\b|eight\b|nine\b|ten\b)))",
    re.I,
)


def name(token):
    return re.sub(r"\s", "", (token or "").replace('"', "")).lower()


def label(value):
    return (
        value
        if len(value) <= 64 and re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", value)
        else ""
    )


def field(reference, qualifier):
    parts = name(reference).split(".")
    return "" if len(parts) == 2 and parts[0] != qualifier else label(parts[-1])


def matching_cutoff(question, count, direction):
    mentions = list(CUTOFF.finditer(question.lower()))
    if not mentions:
        return False
    for match in mentions:
        if (
            match[1]
            and AFTER.search(question[match.end() :])
            or match[3]
            and BEFORE.search(question[: match.start()])
        ):
            return False
        value = match[2] or match[3]
        rows = int(value) if value.isdecimal() else SMALL.index(value) + 1
        order = (
            "top"
            if (match[1] or match[4]) in {"top", "highest", "largest", "most"}
            else "bottom"
        )
        if rows != int(count) or order != direction:
            return False
    return True


def ranking_fields(sql, question):
    if (
        not isinstance(sql, str)
        or len(sql) > 4096
        or not isinstance(question, str)
        or len(question) > 2000
    ):
        return None
    if any(token != token.lower() for token in re.findall(r'"([^\"]*)"', sql)):
        return None
    match = QUERY.fullmatch(sql.strip())
    if match is None:
        return None
    terms = match.groupdict()
    count = terms["limit"] or terms["fetch"]
    direction = "top" if name(terms["direction"]) == "desc" else "bottom"
    if not matching_cutoff(question, count, direction):
        return None
    relation = name(terms["relation"]).split(".")
    if len(relation) == 2 and relation[0] != "public":
        return None
    source = label(relation[-1])
    qualifier = name(terms["alias"]) or source
    group = field(terms["key"], qualifier)
    if (
        not source
        or not group
        or terms["group"] != "1"
        and field(terms["group"], qualifier) != group
    ):
        return None
    metric = name(terms["metric"])
    measure = "count" if metric == "count(*)" else "total"
    amount = field(metric[4:-1], qualifier) if measure == "total" else ""
    if measure == "total" and (not amount or amount == group):
        return None
    score, alias = name(terms["score"]), name(terms["scoreLabel"])
    if (
        alias
        and alias == (name(terms["keyLabel"]) or group)
        or score not in {"2", alias, metric}
    ):
        return None
    return {
        "source": source,
        "group": group,
        "measure": measure,
        "field": amount,
        "direction": direction,
        "number": count,
        "ties": "",
    }
