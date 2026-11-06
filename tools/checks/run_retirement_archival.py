"""Run exactly the nine archival guards inside the bounded native container."""

import json
import os
from pathlib import Path
import sys
import unittest

EXPECTED_IDS = (
    "test_retirement_archival.ArchiveGuards.test_archive_paths_links_duplicate_members_and_capacity_fail_closed",
    "test_retirement_archival.ArchiveGuards.test_bad_manifest_unknown_file_and_non_dump_rejected_before_output",
    "test_retirement_archival.ArchiveGuards.test_default_recovery_has_no_private_reads_or_database_actions",
    "test_retirement_archival.ArchiveGuards.test_missing_and_duplicate_profile_values_fail_closed",
    "test_retirement_archival.ArchiveGuards.test_normal_roundtrip_checks_keys_chain_and_expected_protected_head",
    "test_retirement_archival.ArchiveGuards.test_rehashed_wrong_keys_broken_signatures_and_chain_do_not_become_valid",
    "test_retirement_archival.ArchiveGuards.test_self_consistent_old_or_foreign_head_cannot_satisfy_expected_head",
    "test_retirement_archival.ArchiveGuards.test_total_host_restore_remains_closed_even_for_valid_old_bundle_or_boolean",
    "test_retirement_archival.CaptureGuards.test_dump_is_inside_same_gate_and_all_failure_paths_release_or_poison",
)


def identities(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from identities(item)
        else:
            yield item.id()


def main() -> int:
    if sys.platform != "linux" or os.geteuid() != 1000:
        raise RuntimeError("archival_native_UID1000_required")
    root = Path(__file__).resolve().parents[2]
    # The image supplies the locked dependencies; no host packages are imported.
    # Both roots are required for ops.retirement and retirement imports.
    sys.path[:0] = [str(root), str(root / "backend")]
    import test_retirement_archival

    suite = unittest.defaultTestLoader.loadTestsFromModule(test_retirement_archival)
    observed = sorted(identities(suite))
    if observed != list(EXPECTED_IDS) or suite.countTestCases() != 9:
        raise RuntimeError("archival_exact9_collection_changed")
    # Keep diagnostics and the final structured result on one ordered pipe.
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=1).run(suite)
    counts = {
        "tests": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
    }
    passed = result.wasSuccessful() and not result.skipped and result.testsRun == 9
    print(json.dumps({"status": "passed" if passed else "failed", **counts}))
    return int(not passed)


if __name__ == "__main__":
    raise SystemExit(main())
