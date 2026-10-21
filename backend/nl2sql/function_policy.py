"""Approved pure analytical functions; unknown/user-defined calls fail closed.

The database role remains the independent control. Do not expand this set to
make an arbitrary model output work; review semantics and add adversarial tests.
Names here are SQLGlot AST names, which differ from some PostgreSQL spellings.
"""

from sqlglot import exp

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
