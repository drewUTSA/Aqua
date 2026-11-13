"""Closed backup-client models in two fresh Python namespaces, no services."""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

GROUPS = {
    "bridge46": (
        "authority_bridge_test",
        "authority_decrypt_test",
        "authority_verifier_test",
        "authority_cleanup_test",
    ),
    "sql10": ("authority_sql_model_test",),
}
EXPECTED_IDS = (
    "authority_bridge_test.BridgeTests.test_both_keys_chain_and_pinned_runtime_are_required",
    "authority_bridge_test.BridgeTests.test_changed_after_head_refuses_capture_and_removes_only_owned_pending",
    "authority_bridge_test.BridgeTests.test_changed_key_even_with_rehashed_member_is_rejected",
    "authority_bridge_test.BridgeTests.test_cipher_replacement_during_verification_is_not_published_or_deleted",
    "authority_bridge_test.BridgeTests.test_default_CLI_has_zero_server_private_key_export_or_write_actions",
    "authority_bridge_test.BridgeTests.test_metadata_rejects_expired_unstopped_forged_head_and_total_host_claims",
    "authority_bridge_test.BridgeTests.test_mismatched_authenticated_export_digest_refuses_and_cleans_pending",
    "authority_bridge_test.BridgeTests.test_modeled_capture_and_recovered_copy_never_claim_offhost_or_RPO0",
    "authority_bridge_test.BridgeTests.test_resolved_checkout_alias_cannot_receive_an_authority_backup",
    "authority_bridge_test.BridgeTests.test_restore_callback_missing_or_misbound_or_incomplete_is_not_green",
    "authority_bridge_test.BridgeTests.test_reviewed_primitive_bytes_and_AGE_SSH_pins_are_preserved",
    "authority_bridge_test.BridgeTests.test_same_old_archive_cannot_select_its_own_trusted_head",
    "authority_bridge_test.BridgeTests.test_transport_is_closed_to_arbitrary_stage_or_action",
    "authority_cleanup_test.UncertainCleanupGuards.test_known_ID_and_name_both_absent_resolve_uncertainty",
    "authority_cleanup_test.UncertainCleanupGuards.test_lost_create_response_missing_name_stays_uncertain_and_retains_socket",
    "authority_cleanup_test.UncertainCleanupGuards.test_lost_response_matching_owned_object_resolves_ID_and_is_removed",
    "authority_cleanup_test.UncertainCleanupGuards.test_malformed_create_response_never_becomes_absence",
    "authority_cleanup_test.UncertainCleanupGuards.test_mismatched_labels_do_not_resolve_or_remove_uncertain_object",
    "authority_cleanup_test.UncertainCleanupGuards.test_returned_ID_is_retained_before_missing_initial_verification",
    "authority_decrypt_test.DecryptTests.test_modeled_output_returns_only_after_success_exit",
    "authority_decrypt_test.DecryptTests.test_nonzero_auth_exit_never_returns_earlier_plaintext",
    "authority_decrypt_test.DecryptTests.test_operation_SIGTERM_then_repeat_during_owned_cleanup_is_finite",
    "authority_decrypt_test.DecryptTests.test_oversize_and_stalled_owned_processes_are_stopped",
    "authority_sql_model_test.AuthorityModels.test_complete_signed_model_requires_all_six_tables_original_floors_and_pages",
    "authority_sql_model_test.AuthorityModels.test_original_account_manifest_crosses_128_entry_page_boundary",
    "authority_sql_model_test.AuthorityModels.test_page_owner_floor_fingerprint_and_privilege_mutations_fail",
    "authority_sql_model_test.AuthorityModels.test_pending_unacknowledged_or_rewound_control_never_validates",
    "authority_sql_model_test.AuthorityModels.test_signed_history_floor_cannot_be_reconstructed_to_another_value",
    "authority_sql_model_test.AuthorityModels.test_truncated_or_tampered_public_chain_is_not_accepted",
    "authority_sql_model_test.RoleCapTests.test_failed_post_release_control_cannot_pass_or_expose_error",
    "authority_sql_model_test.RoleCapTests.test_first_authenticated_held_then_same_DSN_after_close_control",
    "authority_sql_model_test.RoleCapTests.test_keeps_53300_and_accepts_only_fixed_operational_startup_limit",
    "authority_sql_model_test.RoleCapTests.test_rejects_wrong_role_password_endpoint_generic_extra_and_oversize",
    "authority_verifier_test.DurableProbeGuards.test_actual_own_python_import_failure_emits_no_exception_text",
    "authority_verifier_test.DurableProbeGuards.test_bootstrap_rejects_invalid_archive_with_fixed_metadata_only",
    "authority_verifier_test.DurableProbeGuards.test_codes_are_only_existing_literal_failures_or_fixed_unknown",
    "authority_verifier_test.DurableProbeGuards.test_create_failure_and_started_probe_failure_keep_distinct_safe_phases",
    "authority_verifier_test.DurableProbeGuards.test_exact_known_failure_is_forwarded_with_same_start_caps",
    "authority_verifier_test.DurableProbeGuards.test_unrecognized_extra_or_dynamic_output_stays_RAM",
    "authority_verifier_test.OrderedRestoreGuards.test_first_table_failure_stops_without_loading_subsequent_tables",
    "authority_verifier_test.OrderedRestoreGuards.test_missing_duplicate_or_extra_table_is_rejected_before_data",
    "authority_verifier_test.OrderedRestoreGuards.test_naive_multi_table_selection_keeps_TOC_order_and_reproduces_FK_conflict",
    "authority_verifier_test.OrderedRestoreGuards.test_new_restore_selects_one_table_in_exact_parent_order_same_role_data",
    "authority_verifier_test.VerifierGuards.test_actual_controller_SIGTERM_and_repeat_finishes_red_owned_cleanup",
    "authority_verifier_test.VerifierGuards.test_default_loader_and_controller_do_not_execute_any_action",
    "authority_verifier_test.VerifierGuards.test_explicit_CLI_rejects_unreviewed_manifest_before_input_or_transport",
    "authority_verifier_test.VerifierGuards.test_framing_is_keyless_and_rejects_truncation_or_trailing_data",
    "authority_verifier_test.VerifierGuards.test_incomplete_or_extra_table_dump_is_rejected_before_restore",
    "authority_verifier_test.VerifierGuards.test_loader_checks_every_source_byte_before_compiling_or_transport",
    "authority_verifier_test.VerifierGuards.test_no_receipt_only_callback_can_claim_actual_SQL_restore",
    "authority_verifier_test.VerifierGuards.test_public_expected_keys_exclude_private_key_members",
    "authority_verifier_test.VerifierGuards.test_restore_uses_six_exact_tables_and_non_super_INSERT_only_role",
    "authority_verifier_test.VerifierGuards.test_same_name_new_ID_and_renamed_original_ID_cannot_report_cleanup",
    "authority_verifier_test.VerifierGuards.test_source_archive_links_traversal_duplicates_and_unhashed_changes_fail",
    "authority_verifier_test.VerifierGuards.test_source_recheck_rejects_changed_files_before_ssh",
    "authority_verifier_test.VerifierGuards.test_unowned_id_and_daemon_failure_never_become_absence",
)


def identities(suite):
    for case in suite:
        if isinstance(case, unittest.TestSuite):
            yield from identities(case)
        else:
            yield case.id()


def expected(group):
    modules = set(GROUPS[group])
    return tuple(value for value in EXPECTED_IDS if value.split(".", 1)[0] in modules)


def valid_counts(value, count):
    return (
        type(value) is dict
        and set(value) == {"status", "tests", "failures", "errors", "skipped"}
        and value["status"] == "passed"
        and all(
            type(value[key]) is int
            for key in ("tests", "failures", "errors", "skipped")
        )
        and value["tests"] == count
        and value["failures"] == value["errors"] == value["skipped"] == 0
    )


def child(group):
    here = Path(__file__).resolve().parents[2] / "ops/retirement/backup_client"
    sys.path.insert(0, str(here))
    suite = unittest.defaultTestLoader.loadTestsFromNames(GROUPS[group])
    if tuple(sorted(identities(suite))) != expected(group):
        raise RuntimeError("backup_closed_collection_changed")
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=1).run(suite)
    counts = {
        "tests": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
    }
    passed = (
        result.wasSuccessful()
        and not result.skipped
        and result.testsRun == len(expected(group))
    )
    print(json.dumps({"status": "passed" if passed else "failed", **counts}))
    return int(not passed)


def main():
    if sys.platform != "linux" or os.geteuid() != 1000:
        raise RuntimeError("backup_native_closed_UID1000_required")
    if len(sys.argv) == 3 and sys.argv[1] == "--group" and sys.argv[2] in GROUPS:
        return child(sys.argv[2])
    if sys.argv[1:]:
        raise RuntimeError("backup_closed_groups_only")
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for group in GROUPS:
        # Known source-only models; separate processes prevent vendor namespace
        # reuse. The enclosing native wrapper retains its original 60s/128MiB cap.
        result = subprocess.run(
            [
                sys.executable,
                "-E",
                "-s",
                "-B",
                str(Path(__file__).resolve()),
                "--group",
                group,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=25,
            close_fds=True,
        )
        if len(result.stdout) > 65536:
            raise RuntimeError("backup_model_output_capacity")
        value = json.loads(result.stdout.splitlines()[-1])
        if result.returncode or not valid_counts(value, len(expected(group))):
            raise RuntimeError("backup_model_group_failed")
        for name in totals:
            totals[name] += value[name]
        sys.stdout.buffer.write(result.stdout)
        sys.stdout.buffer.flush()
    passed = totals == {"tests": 56, "failures": 0, "errors": 0, "skipped": 0}
    print(
        json.dumps({"status": "passed" if passed else "failed", **totals}), flush=True
    )
    return int(not passed)


if __name__ == "__main__":
    raise SystemExit(main())
