"""Run only36 fixed capture/normal fixture models; no Docker or PG inside."""

import json
import os
from pathlib import Path
import sys
import unittest

MODULES = (
    "test_retirement_capture",
    "test_retirement_normal",
    "test_normal_runtime_startup",
    "test_retirement_normal_protocol",
    "test_normal_runtime_failure",
)
EXPECTED_IDS = (
    "test_normal_runtime_failure.FailureBoundary.test_secret_HTTP_failure_reports_closed_metadata_and_cannot_be_green",
    "test_normal_runtime_startup.StartupExitGuards.test_any_admitted_private_response_stays_red",
    "test_normal_runtime_startup.StartupExitGuards.test_closed_exit_requires_nonzero_reaped_PID_no_listener_no_private_response",
    "test_normal_runtime_startup.StartupExitGuards.test_closed_path_keeps_both_physical_inode_identity_checks",
    "test_normal_runtime_startup.StartupExitGuards.test_import_config_unknown_and_oversized_stderr_cannot_count_as_restore_denial",
    "test_normal_runtime_startup.StartupExitGuards.test_zero_exit_or_surviving_listener_is_not_a_valid_restore_denial",
    "test_retirement_capture.BaseOwnedIdentityGuards.test_dump_executes_only_the_inspected_retained_ID",
    "test_retirement_capture.BaseOwnedIdentityGuards.test_every_base_role_remembers_returned_ID_before_first_inspection",
    "test_retirement_capture.BaseOwnedIdentityGuards.test_foreign_ID_cannot_replace_known_owned_name",
    "test_retirement_capture.BaseOwnedIdentityGuards.test_lost_create_resolves_only_matching_metadata_then_dual_absence",
    "test_retirement_capture.BaseOwnedIdentityGuards.test_renamed_owned_PG_never_becomes_cleanup_success",
    "test_retirement_capture.BaseOwnedIdentityGuards.test_unresolved_lost_create_absence_is_red",
    "test_retirement_capture.CaptureDeadlineGuards.test_existing_prep_alarm_is_rejected_until_explicit_phase_transition",
    "test_retirement_capture.CaptureDeadlineGuards.test_failure_frame_emits_only_closed_category_never_private_message",
    "test_retirement_capture.CaptureGuards.test_alarm_cancellation_is_controlled_and_latched_during_cleanup",
    "test_retirement_capture.CaptureGuards.test_capture_uses_owned_paths_only_and_actual_compiled_image",
    "test_retirement_capture.CaptureGuards.test_cleanup_retries_new_clear_role_after_failed_flag_operation",
    "test_retirement_capture.CaptureGuards.test_default_invocation_has_zero_actions",
    "test_retirement_capture.CaptureGuards.test_no_capture_process_before_append_barrier",
    "test_retirement_capture.CaptureGuards.test_original_capture_ID_and_name_both_absent_before_clean",
    "test_retirement_capture.CaptureGuards.test_renamed_capture_remains_unclean_without_blind_removal",
    "test_retirement_capture.CaptureGuards.test_valid_returned_capture_ID_is_retained_before_inspection_failure",
    "test_retirement_capture.MissingInspectFormattingGuards.test_actual_single_newline_is_empty_only_with_exact_owned_NoSuch_error",
    "test_retirement_normal.NormalGuards.test_PG_control_uses_current_inspected_retained_ID_only",
    "test_retirement_normal.NormalGuards.test_all_five_roles_refuse_before_flag_barrier",
    "test_retirement_normal.NormalGuards.test_defaults_start_no_server_or_pool",
    "test_retirement_normal.NormalGuards.test_every_role_has_only_owned_RO_sources_socket_no_installed_keys",
    "test_retirement_normal.NormalGuards.test_exact_compiled_runtime_subset_is_public_and_root_pinned",
    "test_retirement_normal.NormalGuards.test_known_ID_retained_before_first_inspection_failure",
    "test_retirement_normal.NormalGuards.test_renamed_role_and_unresolved_lost_create_remain_red",
    "test_retirement_normal_protocol.Framing.test_control_header128_is_preserved",
    "test_retirement_normal_protocol.Framing.test_fixed_recovery_public_keys_exceed128_and_body_remains_framed",
    "test_retirement_normal_protocol.Framing.test_old128_rejects_known_pool_style_line_new_seed_keeps_private_frame",
    "test_retirement_normal_protocol.Framing.test_public_json_over16KiB_is_rejected",
    "test_retirement_normal_protocol.Framing.test_seed_total1MiB_includes_private_reads",
    "test_retirement_normal_protocol.Framing.test_unknown_control_traceback_and_wrong_mode_json_fail_closed",
)


def identities(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from identities(item)
        else:
            yield item.id()


def checked_suite(suite):
    if sorted(identities(suite)) != list(EXPECTED_IDS) or suite.countTestCases() != 36:
        raise RuntimeError("fixture_exact36_collection_changed")
    return suite


def main() -> int:
    if sys.argv[1:] or sys.platform != "linux" or os.geteuid() != 1000:
        raise RuntimeError("fixture_native_closed_UID1000_required")
    here = Path(__file__).resolve().parent
    root = here.parents[1]
    sys.path[:0] = [str(here), str(root), str(root / "backend")]
    suite = checked_suite(unittest.defaultTestLoader.loadTestsFromNames(MODULES))
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=1).run(suite)
    counts = {
        "tests": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
    }
    passed = result.wasSuccessful() and not result.skipped and result.testsRun == 36
    print(json.dumps({"status": "passed" if passed else "failed", **counts}))
    return int(not passed)


if __name__ == "__main__":
    raise SystemExit(main())
