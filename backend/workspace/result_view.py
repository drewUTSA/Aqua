"""Employee delivery omits generated SQL; internal execution/history retain it."""

from workspace.ranking_fields import ranking_fields

FIELDS = frozenset(
    {
        "status",
        "model",
        "message",
        "tables",
        "visualizations",
        "kpis",
        "error",
        "result_metadata",
        "presentation",
    }
)


def employee_result(value: dict | None) -> dict | None:
    """Project only after owner and current dataset access have been checked.

    The empty compatibility field supports older clients without disclosing the
    executed or rejected statement. Never alter the saved internal response.
    """
    if value is None:
        return None
    result = {key: item for key, item in value.items() if key in FIELDS}
    result["sql"] = ""
    error = result.get("error")
    if isinstance(error, dict):
        result["error"] = {
            key: error[key] for key in ("code", "message", "retryable") if key in error
        }
    tables = value.get("tables")
    if (
        value.get("status") == "success"
        and isinstance(tables, list)
        and len(tables) == 1
        and isinstance(tables[0], dict)
    ):
        fields = ranking_fields(value.get("sql"), tables[0].get("title"))
        if fields is not None:
            result["rank_fields"] = fields
    return result
