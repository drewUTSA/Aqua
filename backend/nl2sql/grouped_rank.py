"""Resolve one authorized fact-table group and measure, then compile its membership and display."""

from dataclasses import dataclass
import re

from nl2sql.answer_size import AnswerSize
from nl2sql.display import header
from nl2sql.group_rank_language import Ranking, parse
from nl2sql.metadata_policy import BANK_TABLES, COMMENTS
from nl2sql.schema import Column, Schema, Table
from nl2sql.validate import HIDDEN_COLUMNS

_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{0,62}")
_NUMERIC = {"smallint", "integer", "bigint", "numeric", "decimal"}
_GROUP_TYPES = _NUMERIC | {
    "text",
    "character varying",
    "character",
    "date",
    "boolean",
    "uuid",
}
_BANK_NAMES = {
    "trans": "transaction",
    "disp": "disposition",
    "order": "standing order",
    "client": "customer",
}


def _type(column: Column) -> str:
    # PostgreSQL format_type reports typmods for ordinary fixed-precision
    # decimals and bounded text. No type name is interpolated into SQL.
    match = re.fullmatch(
        r"(numeric|decimal)\([0-9]+(?:,\s*-?[0-9]+)?\)|(character(?: varying)?)\([0-9]+\)",
        column.type,
    )
    return (match[1] or match[2]) if match else column.type


def _forms(name: str) -> set[str]:
    """Conservative English inflection of the final word of a catalog label."""
    name = name.replace("_", " ")
    if name.endswith("ies"):
        return {name, name[:-3] + "y"}
    if name.endswith(("ches", "shes", "xes", "sses")):
        return {name, name[:-2]}
    if name.endswith("s") and not name.endswith(("us", "ss")):
        return {name, name[:-1]}
    if re.search(r"[^aeiou]y$", name):
        return {name, name[:-1] + "ies"}
    return {name, name + ("es" if name.endswith(("s", "x", "ch", "sh")) else "s")}


def _table_labels(name: str, bank: bool) -> set[str]:
    labels = _forms(name)
    if bank and name in _BANK_NAMES:
        labels |= _forms(_BANK_NAMES[name])
    return labels


def _column_labels(table: Table, column: Column, bank: bool) -> set[str]:
    labels = _forms(column.name)
    if column.name.endswith("_id"):
        base = column.name[:-3]
        labels |= _forms(base) | _forms(base + "_identifier")
    if bank:
        # Only the existing approved glossary supplies additional column names.
        label = header(COMMENTS.get(f"{table.name}.{column.name}", ""))
        if label:
            labels |= _forms(label.lower())
    return labels


def _qualified(labels: set[str], sources: set[str]) -> set[str]:
    return labels | {f"{source} {label}" for source in sources for label in labels}


@dataclass(frozen=True)
class Measure:
    column: Column | None  # None is COUNT(*) over source rows.
    output: str
    names: frozenset[str]


def _measures(table: Table, sources: set[str], bank: bool, phrase: str):
    records = sources | {"row", "rows", "record", "records"}
    counts = {"count", "row count", "record count"}
    counts |= {f"{label} {word}" for label in records for word in ("count", "counts")}
    counts |= {
        f"{prefix} {label}" for prefix in ("count of", "number of") for label in records
    }
    if phrase in counts:
        output = (
            "transaction" if bank and table.name == "trans" else table.name
        ) + "_count"
        yield Measure(None, output, frozenset(counts | {output.replace("_", " ")}))
    for column in table.columns:
        names = _qualified(_column_labels(table, column, bank), sources)
        sums = {
            f"{prefix} {name}"
            for prefix in ("total", "sum of", "total of")
            for name in names
        }
        sums |= {f"{name} {word}" for name in names for word in ("total", "totals")}
        if phrase in sums:
            yield Measure(column, "total_" + column.name, frozenset(sums))


@dataclass(frozen=True)
class Binding:
    table: Table
    group: Column
    group_names: frozenset[str]
    measure: Measure


def _bind(intent: Ranking, schema: Schema, selected: tuple[str, ...]) -> Binding | None:
    bank = schema.allowed_tables == BANK_TABLES
    bindings = []
    for table in schema.tables.values():
        sources = _table_labels(table.name, bank)
        if intent.source and intent.source.removesuffix(" table") not in sources:
            continue
        for group in table.columns:
            short_names = _column_labels(table, group, bank)
            names = _qualified(short_names, sources)
            if intent.group not in names:
                continue
            for measure in _measures(table, sources, bank, intent.measure):
                bindings.append(Binding(table, group, frozenset(names), measure))
    # Resolve ambiguity over the visible schema before applying retrieval. A
    # narrowed prompt must never turn an ambiguous business term into a fact.
    if len(bindings) != 1:
        return None
    binding = bindings[0]
    table, group, measure = binding.table, binding.group, binding.measure
    if (
        table.name not in selected
        or not group.not_null
        or _type(group) not in _GROUP_TYPES
    ):
        return None
    if measure.column:
        if (
            not measure.column.not_null
            or _type(measure.column) not in _NUMERIC
            or measure.column == group
        ):
            return None
        if measure.column.name == "id" or measure.column.name.endswith("_id"):
            return None
        units = {c.name for c in table.columns} & {
            "currency",
            "currency_code",
            "unit",
            "unit_code",
        }
        if units:
            return None
    physical = [group.name] + ([measure.column.name] if measure.column else [])
    if any((table.name, col) in HIDDEN_COLUMNS for col in physical):
        return None
    if not all(
        _IDENTIFIER.fullmatch(s) for s in [table.name, *physical, measure.output]
    ):
        return None
    # An unrestricted entity population can contain parents with no fact
    # rows. This single-table compiler needs an explicit fact scope for it.
    parent = group.name.removesuffix("_id")
    if (
        not intent.source
        and parent != table.name
        and (group.name.endswith("_id") or parent in schema.tables)
    ):
        if intent.group in _column_labels(table, group, bank):
            return None
    return binding


def _field(label: str, binding: Binding, plan: Ranking) -> str | None:
    label = label.removeprefix("the ").removeprefix("their ")
    fields = set()
    if label in binding.group_names:
        fields.add("group_key")
    if label in binding.measure.names or label in {
        "count" if binding.measure.column is None else "total",
        "ranking value",
    }:
        fields.add("score")
    if (
        label == "rank"
        and plan.policy != "exact"
        and not any(c.name == "rank" for c in binding.table.columns)
    ):
        fields.add("position")
    return fields.pop() if len(fields) == 1 else None


_DIRECTIONS = {
    "ascending": "ASC",
    "asc": "ASC",
    "descending": "DESC",
    "desc": "DESC",
    "lowest first": "ASC",
    "highest first": "DESC",
}


def _sort(part: str, binding: Binding, plan: Ranking) -> str | None:
    match = re.fullmatch(
        r"(.+?) (ascending|descending|asc|desc|lowest first|highest first)(?: order)?",
        part,
    )
    if not match:
        return "group_key ASC" if _field(part, binding, plan) == "group_key" else None
    field = _field(match[1].removesuffix(" in"), binding, plan)
    return f"{field} {_DIRECTIONS[match[2]]}" if field else None


@dataclass(frozen=True)
class CompiledRanking:
    sql: str
    size: AnswerSize


def compile_grouped_rank(
    question: str, schema: Schema, selected: tuple[str, ...]
) -> CompiledRanking | None:
    intent = parse(question)
    binding = _bind(intent, schema, selected) if intent else None
    if not binding:
        return None
    measure = binding.measure
    outputs = {
        "group_key": binding.group.name,
        "score": measure.output,
        "position": "rank",
    }
    fields = ["group_key", "score"]
    if intent.projection:
        fields = [
            _field(label, binding, intent)
            for label in re.split(r", and |, | and | then ", intent.projection)
        ]
    if (
        None in fields
        or len(set(fields)) != len(fields)
        or len({outputs[f] for f in fields}) != len(fields)
    ):
        return None
    primary = f"score {intent.direction}"
    group_order = "group_key ASC"
    if intent.tiebreak:
        group_order = _sort(intent.tiebreak, binding, intent)
        if not group_order or not group_order.startswith("group_key "):
            return None
    order = [primary, group_order]
    if intent.display:
        sorts = [
            _sort(part, binding, intent)
            for part in re.split(r", then | then |, | and ", intent.display)
        ]
        if None in sorts:
            return None
        if intent.within_ties and (
            len(sorts) != 1 or not sorts[0].startswith("group_key ")
        ):
            return None
        order = ([primary] if intent.within_ties else []) + sorts
        keys = [term.split()[0] for term in order]
        if len(set(keys)) != len(keys):
            return None
        if "group_key" not in keys:
            order.append(group_order)
    function = {
        "exact": "ROW_NUMBER",
        "cutoff": "RANK",
        "extremum": "RANK",
        "levels": "DENSE_RANK",
    }[intent.policy]
    membership_order = primary + (
        f", {group_order}" if intent.policy == "exact" else ""
    )
    aggregate = f'SUM("{measure.column.name}")' if measure.column else "COUNT(*)"
    projection = ", ".join(f'ranked.{f} AS "{outputs[f]}"' for f in fields)
    display_order = ", ".join(f"ranked.{term}" for term in order)
    sql = (
        f'WITH grouped_values AS (SELECT "{binding.group.name}" AS group_key, {aggregate} AS score '
        f'FROM public."{binding.table.name}" GROUP BY "{binding.group.name}"), '
        f"ranked AS (SELECT group_key, score, {function}() OVER (ORDER BY {membership_order}) AS position FROM grouped_values) "
        f"SELECT {projection} FROM ranked WHERE ranked.position <= {intent.rows} ORDER BY {display_order}"
    )
    size = AnswerSize(
        "single" if intent.policy == "extremum" else "count",
        intent.rows,
        (
            "distinct"
            if intent.policy == "levels"
            else "cutoff" if intent.policy in {"cutoff", "extremum"} else None
        ),
    )
    return CompiledRanking(sql, size)


def grouped_rank_sql(
    question: str, schema: Schema, selected: tuple[str, ...]
) -> str | None:
    plan = compile_grouped_rank(question, schema, selected)
    return plan.sql if plan else None
