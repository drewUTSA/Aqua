"""Rank all parent entities by their number of directly related records."""

import re

from nl2sql.grouped_rank import _BANK_NAMES, _forms
from nl2sql.metadata_policy import BANK_TABLES, PAGILA_TABLES
from nl2sql.scalar_count import _BANK, _PAGILA
from nl2sql.schema import Schema
from nl2sql.validate import HIDDEN_COLUMNS

_REQUEST = re.compile(
    r"(?:please )?(?:which|what) (?P<parent>[a-z]+(?: [a-z]+)?) "
    r"(?:has|have|had) the (?P<side>most|fewest|highest number of|lowest number of|"
    r"largest number of|smallest number of|highest count of|lowest count of) "
    r"(?P<child>[a-z]+(?: [a-z]+)?)(?: records?)?"
    r"(?:[,;]? and (?:how many(?: (?:does|did) (?:it|each) have)?|what (?:is|was) the count))?"
    r"(?:[.,;?]? (?:include|including|keep) (?:all |any |every )?"
    r"(?:ties|(?P<peers>[a-z]+(?: [a-z]+)?) tied for first(?: place)?))?"
)
_NOUNS = {
    manifest: {
        name: table for plural, table in catalog.items() for name in _forms(plural)
    }
    for manifest, catalog in [(BANK_TABLES, _BANK), (PAGILA_TABLES, _PAGILA)]
}


def relationship_count_sql(
    question: str, schema: Schema, selected: tuple[str, ...]
) -> str | None:
    """Use one proven association and count all visible parents, including zeroes."""
    if len(question) > 256 or not question.isascii():
        return None
    text = " ".join(question.lower().split()).rstrip("?.")
    match = _REQUEST.fullmatch(text)
    nouns = _NOUNS.get(schema.allowed_tables)
    if not match or not nouns:
        return None
    parent_name = nouns.get(match["parent"])
    child_name = nouns.get(
        match["child"].removesuffix(" records").removesuffix(" record")
    )
    if not parent_name or not child_name or child_name == parent_name:
        return None
    if match["peers"] and nouns.get(match["peers"]) != parent_name:
        return None
    if parent_name not in selected or child_name not in selected:
        return None
    parent, child = schema.tables[parent_name], schema.tables[child_name]
    key = parent_name + "_id"
    parent_key = next((c for c in parent.columns if c.name == key), None)
    child_key = next((c for c in child.columns if c.name == key), None)
    if (
        not parent_key
        or not parent_key.not_null
        or not child_key
        or parent_key.type not in {"smallint", "integer", "bigint"}
        or child_key.type != parent_key.type
        or (parent_name, key) in HIDDEN_COLUMNS
        or (child_name, key) in HIDDEN_COLUMNS
        or parent_name not in child.references
        or f'PRIMARY KEY ("{key}")' not in parent.constraints
    ):
        return None
    # Reject competing roles (such as initiating and receiving accounts), alternate
    # keys and composite references. A column with a similar name proves no join.
    relations = [c for c in child.constraints if f' REFERENCES "{parent_name}"(' in c]
    if relations != [f'FOREIGN KEY ("{key}") REFERENCES "{parent_name}"("{key}")']:
        return None
    direction = (
        "DESC"
        if match["side"]
        in {"most", "highest number of", "largest number of", "highest count of"}
        else "ASC"
    )
    noun = (
        _BANK_NAMES.get(child_name, child_name)
        if schema.allowed_tables == BANK_TABLES
        else child_name
    )
    output = noun.replace(" ", "_") + "_count"
    # Keep score ties inside the cutoff. Only then sort the peer IDs for display.
    return (
        f'SELECT winners."{key}", winners."{output}" FROM ('
        f'SELECT p."{key}", COUNT(c."{key}") AS "{output}" '
        f'FROM "{parent_name}" AS p LEFT JOIN "{child_name}" AS c ON c."{key}" = p."{key}" '
        f'GROUP BY p."{key}" ORDER BY COUNT(c."{key}") {direction} FETCH FIRST 1 ROW WITH TIES'
        f') AS winners ORDER BY winners."{key}" ASC'
    )
