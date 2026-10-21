"""Approved pure analytical functions; unknown/user-defined calls fail closed.

The database role remains the independent control. Do not expand this set to
make an arbitrary model output work; review semantics and add adversarial tests.
Names here are SQLGlot AST names, which differ from some PostgreSQL spellings.
"""

from sqlglot import exp

from nl2sql.relations import identifier_name

APPROVED_FUNCTIONS = frozenset(
    {
        "abs",
        "acos",
        "and",
        "array_agg",
        "array_size",
        "asin",
        "atan",
        "avg",
        "case",
        "cast",
        "ceil",
        "ceiling",
        "coalesce",
        "concat",
        "concat_ws",
        "count",
        "cume_dist",
        "current_date",
        "current_timestamp",
        "date",
        "date_diff",
        "date_part",
        "date_trunc",
        "dense_rank",
        "exp",
        "exists",
        "extract",
        "first_value",
        "floor",
        "greatest",
        "if",
        "lag",
        "last_value",
        "lead",
        "least",
        "length",
        "ln",
        "log",
        "lower",
        "ltrim",
        "max",
        "min",
        "mod",
        "month",
        "now",
        "nth_value",
        "ntile",
        "nullif",
        "or",
        "percent_rank",
        "percentile_cont",
        "percentile_disc",
        "pow",
        "power",
        "rank",
        "replace",
        "round",
        "row_number",
        "row_to_json",
        "rtrim",
        "sign",
        "sqrt",
        "stddev",
        "stddev_pop",
        "stddev_samp",
        "string_agg",
        "substring",
        "sum",
        "time_to_str",
        "timestamp",
        "timestamp_trunc",
        "to_char",
        "to_date",
        "to_json",
        "to_jsonb",
        "to_timestamp",
        "trim",
        "upper",
        "variance",
        "var_pop",
        "var_samp",
        "generate_series",
        "exploding_generate_series",
        "datediff",
        "ts_or_ds_to_date",
        "md5",
    }
)


def approved_call(node: exp.Func, name: str) -> bool:
    """A safe-looking name in another namespace can be an attacker function."""
    if name not in APPROVED_FUNCTIONS:
        return False
    if isinstance(node.parent, exp.Dot):
        prefix = node.parent.this
        return isinstance(prefix, exp.Identifier) and prefix.name == "pg_catalog"
    return True


# OPERATOR(schema.symbol) and type input/cast functions are executable calls,
# but SQLGlot does not represent them as exp.Func. Keep their explicit spelling
# within reviewed catalog primitives; search_path alone cannot constrain a
# schema-qualified custom operator or type.
APPROVED_EXPLICIT_OPERATORS = frozenset(
    {"+", "-", "*", "/", "%", "^", "=", "<>", "!=", "<", "<=", ">", ">=", "||"}
)
APPROVED_CATALOG_TYPES = frozenset(
    {
        "bool",
        "int2",
        "int4",
        "int8",
        "float4",
        "float8",
        "numeric",
        "text",
        "varchar",
        "bpchar",
        "date",
        "time",
        "timetz",
        "timestamp",
        "timestamptz",
        "interval",
        "bytea",
        "uuid",
        "json",
        "jsonb",
        "bit",
        "varbit",
    }
)


def approved_indirect_call(node: exp.Expression, dialect: str) -> bool:
    """Close operator/type execution paths that have no exp.Func policy check."""
    # regclass/regproc/etc resolve catalog objects even without a FROM clause.
    # They are metadata lookups outside the reviewed dataset relation policy.
    if isinstance(node, exp.ObjectIdentifier):
        return False
    if isinstance(node, exp.Operator):
        operator = node.args.get("operator", "").lower()
        if operator.startswith("pg_catalog."):
            operator = operator[len("pg_catalog.") :]
        return operator in APPROVED_EXPLICIT_OPERATORS
    if isinstance(node, exp.DataType) and node.this == exp.DataType.Type.USERDEFINED:
        kind = node.args.get("kind")
        return (
            isinstance(kind, exp.Dot)
            and isinstance(kind.this, exp.Identifier)
            and isinstance(kind.expression, exp.Identifier)
            and identifier_name(kind.this, dialect) == "pg_catalog"
            and identifier_name(kind.expression, dialect) in APPROVED_CATALOG_TYPES
        )
    return True
