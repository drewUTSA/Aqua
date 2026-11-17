"""Original synthetic saved-result examples; no protected evaluation cases."""

SOURCE = "a" * 64


def response(values=(7, -3.5, None, 7, 1), *, metadata=True, exact=(), truncated=False):
    result = {
        "status": "success",
        "sql": "SELECT PRIVATE_SQL_CANARY",
        "model": "fixture-model",
        "message": "PRIVATE_SUMMARY_CANARY",
        "tables": [
            {
                "id": "result",
                "title": "Synthetic result",
                "columns": [
                    {
                        "key": "value",
                        "label": "Value",
                        "type": "currency",
                        "currency": "USD",
                    }
                ],
                "rows": [{"value": value} for value in values],
            }
        ],
        "visualizations": [],
        "kpis": [],
        "error": None,
    }
    if metadata:
        result["result_metadata"] = {
            "version": 1,
            "source": {"id": SOURCE, "freshness_at": None},
            "generated_at": "2026-11-17T18:00:00+00:00",
            "filters": None,
            "aggregation": "unknown",
            "truncated": truncated,
            "max_rows": 1000,
            "column_units": {"value": None},
            "exact_values": list(exact),
        }
    return result
