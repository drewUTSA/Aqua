"""Synthetic case inventories and JUnit reports for offline runner regressions."""

import xml.etree.ElementTree as ET


def inventory() -> list[dict[str, str]]:
    return [
        {
            "nodeid": f"tests/test_{index}.py::test_case",
            "module": f"tests/test_{index}.py",
            "classname": f"tests.test_{index}",
            "name": "test_case",
        }
        for index in range(8)
    ]


def xml(cases: list[dict[str, str]], extra_passed_subtests: int = 0) -> bytes:
    root = ET.Element("testsuites")
    suite = ET.SubElement(
        root,
        "testsuite",
        tests=str(len(cases) + extra_passed_subtests),
        failures="0",
        errors="0",
        skipped="0",
    )
    for case in cases:
        ET.SubElement(suite, "testcase", classname=case["classname"], name=case["name"])
    return ET.tostring(root)
