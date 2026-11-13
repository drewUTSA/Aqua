"""Run all retained native protocol guards; no skipped platform case is green.

Copy reviewed source into a UID1000-owned writable /checks tmpfs first. Some
guards intentionally create bounded .guard-fixture-* siblings beside themselves.
The source tree needs backend/, ops/retirement/ and this retirement_fixture/;
no recovered historical artifact layout, credentials or Docker socket is used.
"""

import json
import os
from pathlib import Path
import sys
import unittest


def main() -> int:
    """Match the exact original80-case identity and retain ordinary diagnostics."""
    if sys.platform != "linux" or os.geteuid() != 1000:
        raise RuntimeError("retirement_native_UID1000_required")
    here = Path(__file__).resolve().parent
    sys.path[:0] = [str(here.parents[1] / "backend"), str(here / "retirement_fixture")]
    suite = unittest.defaultTestLoader.discover(
        str(here / "retirement_fixture"), pattern="*_test.py"
    )
    collected = suite.countTestCases()
    if collected != 80:
        raise RuntimeError("retirement_native_collection_changed:" + str(collected))
    # Keep diagnostics and the final structured result on one ordered pipe.
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=1).run(suite)
    counts = {
        "tests": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
    }
    passed = result.wasSuccessful() and not result.skipped and result.testsRun == 80
    print(json.dumps({"status": "passed" if passed else "failed", **counts}))
    return int(not passed)


if __name__ == "__main__":
    raise SystemExit(main())
