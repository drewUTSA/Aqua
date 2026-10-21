"""Prevent fixture-specific skips from silently dropping integration coverage."""

from pathlib import Path
import xml.etree.ElementTree as ET


def coverage(output: Path) -> dict:
    """Each collected test must pass in at least one fixture run."""
    all_cases: set[str] = set()
    passed: set[str] = set()
    for dataset in ("bank", "pagila"):
        document = ET.parse(output / (dataset + ".xml"))
        for case in document.iter("testcase"):
            key = case.attrib["classname"] + "::" + case.attrib["name"]
            all_cases.add(key)
            if not any(
                case.find(tag) is not None for tag in ("skipped", "failure", "error")
            ):
                passed.add(key)
    missing = sorted(all_cases - passed)
    if not all_cases or missing:
        raise RuntimeError("fixture matrix left tests unverified: " + repr(missing))
    return {
        "unique_tests": len(all_cases),
        "passed_in_at_least_one_fixture": len(passed),
    }
