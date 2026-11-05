"""Collect the complete backend suite and verify disjoint bounded batch results."""

import argparse
from collections import Counter
import json
from pathlib import Path
import xml.etree.ElementTree as ET

BATCH_COUNT = 4


def plan(cases: list[dict[str, str]]) -> list[dict]:
    """Keep each module together; partition every default-collected case once."""
    if not cases:
        raise RuntimeError("backend_collection_empty")
    identities = [(case["classname"], case["name"]) for case in cases]
    if len(set(identities)) != len(cases) or len(
        {case["nodeid"] for case in cases}
    ) != len(cases):
        raise RuntimeError("backend_collection_duplicate_identity")
    modules = sorted({case["module"] for case in cases})
    for module in modules:
        path = Path(module)
        if (
            path.is_absolute()
            or ".." in path.parts
            or not path.parts
            or path.parts[0] != "tests"
            or path.suffix != ".py"
        ):
            raise RuntimeError("backend_collection_unexpected_module")
    batches = []
    for index in range(min(BATCH_COUNT, len(modules))):
        selected = modules[index::BATCH_COUNT]
        batches.append(
            {
                "id": f"{index + 1:02}",
                "modules": selected,
                "cases": [case for case in cases if case["module"] in selected],
            }
        )
    return batches


def collect(output: Path, deselect: str) -> int:
    """Ask the pinned pytest collector, rather than guessing filename patterns."""
    import pytest
    from _pytest.junitxml import bin_xml_escape, mangle_test_address

    class Inventory:
        def __init__(self) -> None:
            self.cases = []
            self.deselected = []

        def pytest_deselected(self, items: list[pytest.Item]) -> None:
            self.deselected.extend(item.nodeid for item in items)

        def pytest_collection_finish(self, session: pytest.Session) -> None:
            for item in session.items:
                names = mangle_test_address(item.nodeid)
                self.cases.append(
                    {
                        "nodeid": item.nodeid,
                        "module": item.path.relative_to(
                            session.config.rootpath
                        ).as_posix(),
                        "classname": ".".join(names[:-1]),
                        "name": bin_xml_escape(names[-1]),
                    }
                )

    inventory = Inventory()
    status = pytest.main(
        [
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "--deselect=" + deselect,
        ],
        plugins=[inventory],
    )
    if status:
        return int(status)
    if inventory.deselected != [deselect]:
        raise RuntimeError("backend_capacity_deselection_not_exact")
    output.write_text(
        json.dumps({"schema": 1, "batches": plan(inventory.cases)}, indent=2) + "\n"
    )
    return 0


def merge(output: Path, dataset: str, batches: list[dict]) -> dict:
    """Fail closed on missing, duplicate, foreign or malformed JUnit cases."""
    combined = ET.Element("testsuites")
    all_seen: set[tuple[str, str]] = set()
    for batch in batches:
        tree = ET.parse(output / f"{dataset}-batch-{batch['id']}.xml")
        root = tree.getroot()
        if root.tag != "testsuites" or not list(root):
            raise RuntimeError("backend_batch_junit_shape")
        observed = []
        for suite in root:
            if suite.tag != "testsuite":
                raise RuntimeError("backend_batch_junit_shape")
            cases = suite.findall("testcase")
            # Pytest 9 counts successful unittest subtests here without adding
            # testcase nodes. Coverage comes only from exact collected IDs.
            if int(suite.attrib["tests"]) < len(cases):
                raise RuntimeError("backend_batch_junit_count")
            observed.extend(
                (case.attrib["classname"], case.attrib["name"]) for case in cases
            )
            for tag in ("errors", "failures", "skipped"):
                if tag != "skipped" and int(suite.attrib.get(tag, "0")):
                    raise RuntimeError("backend_batch_junit_failure")
                if int(suite.attrib.get(tag, "0")) != sum(
                    len(case.findall("error" if tag == "errors" else tag.rstrip("s")))
                    for case in cases
                ):
                    raise RuntimeError("backend_batch_junit_status_count")
            combined.append(suite)
        expected = [(case["classname"], case["name"]) for case in batch["cases"]]
        if Counter(observed) != Counter(expected) or len(set(observed)) != len(
            observed
        ):
            raise RuntimeError("backend_batch_junit_identity_mismatch")
        if all_seen.intersection(observed):
            raise RuntimeError("backend_batches_overlap")
        all_seen.update(observed)
    if not all_seen:
        raise RuntimeError("backend_batch_junit_empty")
    ET.ElementTree(combined).write(
        output / (dataset + ".xml"), encoding="utf-8", xml_declaration=True
    )
    return {"batches": len(batches), "unique_tests": len(all_seen)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect", required=True, type=Path)
    parser.add_argument("--deselect", required=True)
    args = parser.parse_args()
    raise SystemExit(collect(args.collect, args.deselect))
