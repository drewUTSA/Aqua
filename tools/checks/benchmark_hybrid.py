"""Synthetic identifier-recovery overhead, not real-model accuracy or an SLO."""

from pathlib import Path
import json
import statistics
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from nl2sql.retrieval.hybrid import hybrid_tables  # noqa: E402

names = ["account", "loan", "transaction", "customer", "branch"] + [
    f"fixture_table_{i:04}" for i in range(507)
]
columns = {
    "account": ("balance", "opened_at"),
    "loan": ("principal", "payment"),
    "transaction": ("amount",),
    "customer": ("email",),
    "branch": ("city",),
}
tables = {
    name: SimpleNamespace(
        columns=tuple(
            SimpleNamespace(name=column)
            for column in columns.get(name, ("synthetic_value",))
        )
    )
    for name in names
}
schema = SimpleNamespace(tables=tables, allowed_tables=frozenset(tables))
cases = [
    ("account balance", "account"),
    ("loan principal", "loan"),
    ("transaction amount", "transaction"),
    ("branch city", "branch"),
]
samples, recovered = [], 0
for question, target in cases:
    # Deliberately omit the identifier target to test lexical recovery only.
    nearest = [name for name in names[:5] if name != target]
    assert target not in nearest
    result = hybrid_tables(schema, nearest, question)
    recovered += target in result
    for _ in range(30):
        start = time.perf_counter()
        assert hybrid_tables(schema, nearest, question) == result
        samples.append((time.perf_counter() - start) * 1000)
print(
    json.dumps(
        {
            "kind": "synthetic_identifier_recovery",
            "catalog_tables": len(tables),
            "cases": len(cases),
            "recovered_targets": recovered,
            "top_k": 4,
            "samples": len(samples),
            "median_ms": statistics.median(samples),
            "max_ms": max(samples),
            "additional_provider_calls": 0,
            "real_model_accuracy_measured": False,
        },
        sort_keys=True,
    )
)
