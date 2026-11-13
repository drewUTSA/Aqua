"""Compare the previous repeated catalog scan with request-local join context.

Synthetic metadata only. Times describe this component on the execution host;
they do not measure provider latency, model accuracy or total application scale.
"""

import json
import platform
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from nl2sql.retrieval.graph import select_tables  # noqa: E402


class Columns:
    def __init__(self, names: tuple[str, ...], counter: list[int]) -> None:
        self.names, self.counter = names, counter

    def __iter__(self):
        self.counter[0] += 1
        return iter(SimpleNamespace(name=name) for name in self.names)


def catalog(count: int, counter: list[int]) -> dict:
    return {
        f"t{i}": SimpleNamespace(
            references=frozenset({f"t{i+1}"}) if i + 1 < count else frozenset(),
            columns=Columns(tuple(f"value_{n}" for n in range(8)), counter),
        )
        for i in range(count)
    }


def previous_selection(tables: dict, nearest: list[str]) -> set[str]:
    """Frozen pre-P12 one-step selection algorithm, independent of new helpers."""
    chosen = set(nearest)
    bridges = set()
    for candidate in tables:
        if candidate in chosen:
            continue
        related = {candidate}
        for name, table in tables.items():
            links = set(table.references) | {
                column.name[:-3]
                for column in table.columns
                if column.name.endswith("_id") and column.name[:-3] in tables
            }
            links.discard(name)
            if name == candidate:
                related |= links
            elif candidate in links:
                related.add(name)
        if len((related - {candidate}) & chosen) >= 2:
            bridges.add(candidate)
    return chosen | bridges


def main() -> None:
    rows = []
    for count in (24, 128, 512):
        samples = {"previous": [], "candidate": []}
        visits = {}
        results = {}
        for label in samples:
            for _ in range(5):
                counter = [0]
                data = catalog(count, counter)
                began = time.perf_counter_ns()
                selected = (
                    previous_selection(data, ["t0", "t3", "t6", "t9"])
                    if label == "previous"
                    else select_tables(data, ["t0", "t3", "t6", "t9"], [])
                )
                samples[label].append((time.perf_counter_ns() - began) / 1_000_000)
                visits[label], results[label] = counter[0], selected
        assert results["previous"] <= results["candidate"] <= set(data)
        assert visits["candidate"] == count
        rows.append(
            {
                "tables": count,
                "column_sequence_visits": visits,
                "median_ms": {
                    label: round(statistics.median(values), 4)
                    for label, values in samples.items()
                },
                "selected_tables": {
                    label: len(value) for label, value in results.items()
                },
                "samples_each": 5,
            }
        )
    print(
        json.dumps(
            {
                "status": "passed",
                "python": platform.python_version(),
                "os": platform.system(),
                "processor": platform.processor(),
                "scope": "synthetic retrieval graph only",
                "measurements": rows,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
