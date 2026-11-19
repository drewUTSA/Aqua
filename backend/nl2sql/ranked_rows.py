"""Resolve explicit peer rankings on individual, unfiltered bank records."""

import re

from nl2sql.answer_size import requested_rows
from nl2sql.metadata_policy import BANK_TABLES
from nl2sql.schema import Schema

# Only this reviewed vocabulary can supply identifiers. "Balance" is the
# recorded balance after a transaction, not a group's current account balance.
_FIELDS = {
    "loan": {
        "loan_id": ("id", "ids", "identifier", "identifiers", "loan id", "loan ids"),
        "account_id": ("account id", "account ids"),
        "amount": ("amount", "amounts", "loan amount", "loan amounts"),
        "duration": ("duration", "loan duration", "duration in months"),
        "payments": ("monthly payment", "monthly payments"),
        "date": ("loan date", "date"),
    },
    "trans": {
        "trans_id": (
            "id",
            "ids",
            "identifier",
            "identifiers",
            "transaction id",
            "transaction ids",
        ),
        "account_id": ("account id", "account ids"),
        "amount": ("amount", "amounts", "transaction amount", "transaction amounts"),
        "balance": ("post-transaction balance", "balance after the transaction"),
        "date": ("transaction date", "date"),
    },
}
_SCORES = {"loan": {"amount", "duration", "payments"}, "trans": {"amount", "balance"}}
_IDS = {"loan": "loan_id", "trans": "trans_id"}
_INTEGER = {"integer", "smallint", "bigint"}
_DECIMAL = re.compile(r"numeric(?:\(\d{1,4}(?:,\s*\d{1,4})?\))?")
_SUBJECT = r"(?P<subject>loan ids?|transaction ids?|loans?|transactions?)"
_PEERS = re.compile(
    r",? (?:including|with|keeping|retaining) (?:all |any )?ties(?: at the cutoff)?$"
)
_TOP = re.compile(
    rf"(?:the )?(?P<end>top|bottom) (?P<count>[a-z0-9-]+) {_SUBJECT} (?:ranked )?by (?:the |their )?(?P<score>[a-z -]+)"
)
_EXTREME = re.compile(
    rf"(?:(?P<all>all(?: the)?|every) |the )?{_SUBJECT} "
    r"(?P<relation>(?:(?:that|which) )?(?:share|shares|tie for|ties for|are tied for|have|has)|"
    r"sharing|tied for|with|at|matching|having) (?P<article>the )?"
    r"(?P<end>highest|largest|lowest|smallest|maximum|minimum) (?P<score>[a-z -]+)"
)
_VERB = re.compile(r"^(?:please )?(?:which|show(?: me)?|list|return|find|give me) ")
_OUTPUT = re.compile(
    r"(.+?)(?:[.?;,]\s*| and )(?:show(?:ing)?|return(?:ing)?|list(?:ing)?|give|display(?:ing)?) "
    r"(?:only )?(.+)"
)


def _lookup(table: str, phrase: str) -> str | None:
    for column, names in _FIELDS[table].items():
        if phrase in names:
            return column
    return None


def _typed_field(column: str, sql_type: str) -> bool:
    if column == "date":
        return sql_type == "date"
    if column.endswith("_id"):
        return sql_type in _INTEGER
    return sql_type in _INTEGER or _DECIMAL.fullmatch(sql_type) is not None


def ranked_rows_sql(
    question: str, schema: Schema, selected: tuple[str, ...]
) -> str | None:
    """A complete explicit request yields a single authorized query, else ordinary generation."""
    if len(question) > 384 or schema.allowed_tables != BANK_TABLES:
        return None
    text = " ".join(question.lower().split()).removesuffix("?").removesuffix(".")
    if not _VERB.match(text):
        return None
    request = _VERB.sub("", text, count=1)
    fields = None
    if output := _OUTPUT.fullmatch(request):
        request, fields = output.groups()
    elif projection := re.fullmatch(
        r"(.+?) for ((?:all |every |the (?:top|bottom) |(?:loans|transactions) (?:sharing|tied) ).+)",
        request,
    ):
        fields, request = projection.groups()
        fields = fields.removeprefix("only ")

    request, peer_suffix = _PEERS.subn("", request)
    if top := _TOP.fullmatch(request):
        count = requested_rows(top["count"])
        if not peer_suffix or count is None:
            return None
        match, rows = top, count
    elif extreme := _EXTREME.fullmatch(request):
        explicit_peers = re.search(r"shar|ti(?:e|ed)", extreme["relation"])
        if not (peer_suffix or explicit_peers or extreme["all"]) or (
            not explicit_peers and not extreme["article"]
        ):
            return None
        match, rows = extreme, 1
    else:
        return None

    table = "loan" if match["subject"].startswith("loan") else "trans"
    if table not in selected:
        return None
    metric = _lookup(table, match["score"])
    if metric not in _SCORES[table]:
        return None

    named_id = match["subject"].endswith((" id", " ids"))
    if fields is None:
        if not named_id:
            return None
        columns = [_IDS[table]]
    else:
        fields = re.sub(r",? in that order$", "", fields)
        parts = re.split(r",\s*(?:(?:and|then) )?| (?:and|then) ", fields)
        columns = []
        for token in parts:
            column = _lookup(table, token.removeprefix("the ").removeprefix("their "))
            if column is None or column in columns:
                return None
            columns.append(column)
        if named_id and _IDS[table] not in columns:
            return None
    relation = schema.tables[table]
    identifier = _IDS[table]
    key_forms = {f"PRIMARY KEY ({identifier})", f'PRIMARY KEY ("{identifier}")'}
    if key_forms.isdisjoint(relation.constraints):
        return None
    catalog = {c.name: c.type for c in relation.columns}
    inner_columns = list(dict.fromkeys([*columns, metric, identifier]))
    if not all(_typed_field(c, catalog.get(c, "")) for c in inner_columns):
        return None
    direction = (
        "DESC" if match["end"] in {"top", "highest", "largest", "maximum"} else "ASC"
    )
    # The primary key orders the display only. Adding it to the inner ranking
    # would remove peers. Neither the key nor the score is added to the output.
    return (
        f"SELECT {', '.join(columns)} FROM (SELECT {', '.join(inner_columns)} "
        f"FROM {table} WHERE {metric} IS NOT NULL ORDER BY {metric} {direction} "
        f"FETCH FIRST {rows} ROWS WITH TIES) AS ranked "
        f"ORDER BY {metric} {direction}, {identifier} ASC"
    )
