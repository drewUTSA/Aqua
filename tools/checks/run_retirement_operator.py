"""Run one closed set of reviewed operator models; no Docker/PG is reachable here."""

import json
import os
from pathlib import Path
import sys
import unittest

MODULES = (
    "test_retirement_operator",
    "test_retirement_scope",
    "test_retirement_install_fsync",
    "test_retirement_singleton",
    "test_retirement_provisioning",
    "test_retirement_installer_recovery",
)
EXPECTED_IDS = (
    "test_retirement_install_fsync.InstallFsyncTests.test_code_parent_syncs_precede_initializer_and_success",
    "test_retirement_install_fsync.InstallFsyncTests.test_directory_validation_precedes_open",
    "test_retirement_install_fsync.InstallFsyncTests.test_each_code_sync_failure_cleans_without_initializer_or_receipt",
    "test_retirement_install_fsync.InstallFsyncTests.test_exclusive_creation_preserves_existing_public_root",
    "test_retirement_install_fsync.InstallFsyncTests.test_root_parent_sync_precedes_materialize_and_SQL",
    "test_retirement_install_fsync.InstallFsyncTests.test_root_sync_failure_stops_before_keys_or_SQL",
    "test_retirement_install_fsync.InstallFsyncTests.test_verified_descriptor_rejects_owner_mode_type_and_identity",
    "test_retirement_installer_recovery.AckHostImportTests.test_exact_approved_host_source_imports_before_any_private_open",
    "test_retirement_installer_recovery.AckHostImportTests.test_retained_shallow_path_reproduces_failure_before_any_private_open",
    "test_retirement_installer_recovery.ArchiveInputTests.test_full_approved_source_accepts_exact_large_runtime_asset",
    "test_retirement_installer_recovery.ArchiveInputTests.test_large_asset_exception_never_accepts_different_bytes",
    "test_retirement_installer_recovery.ArchiveInputTests.test_other_large_members_remain_rejected_and_source_pin_is_required",
    "test_retirement_installer_recovery.ChildOwnershipTests.test_exact_recovery_child_is_owned_with_four_readonly_mounts",
    "test_retirement_installer_recovery.ChildOwnershipTests.test_family_or_role_crossovers_are_foreign",
    "test_retirement_installer_recovery.ChildOwnershipTests.test_foreign_label_image_production_mount_or_writable_mount_is_rejected",
    "test_retirement_installer_recovery.CleanLaunchTests.test_direct_clean_import_uses_only_explicit_reviewed_root",
    "test_retirement_installer_recovery.ControllerOrderingTests.test_actual_CLI_dispatch_follows_keeper_release_and_final_receipt",
    "test_retirement_installer_recovery.ControllerOrderingTests.test_unready_recovery_stays_red_and_still_cleans_exact_fixture",
    "test_retirement_installer_recovery.MountTargetTests.test_actual_create_places_all_targets_before_parent_fsync",
    "test_retirement_installer_recovery.MountTargetTests.test_exact_materialize_targets_are_empty_single_link_owner0600_files",
    "test_retirement_installer_recovery.MountTargetTests.test_existing_target_is_not_overwritten_or_followed",
    "test_retirement_installer_recovery.ProfileTests.test_create_only_profile_cannot_overwrite_or_extend_expiry",
    "test_retirement_installer_recovery.ProfileTests.test_foreign_or_overprivileged_DSN_is_rejected_before_write",
    "test_retirement_installer_recovery.ProfileTests.test_profile_binds_all_inputs_and_never_copies_authority_keys",
    "test_retirement_installer_recovery.ProfileTests.test_stale_or_accepted_head_is_not_genesis_profile",
    "test_retirement_installer_recovery.PublicErrorTests.test_arbitrary_private_text_arguments_and_subclasses_never_escape",
    "test_retirement_installer_recovery.PublicErrorTests.test_only_exact_source_known_preflight_categories_are_retained",
    "test_retirement_installer_recovery.ReceiptTests.test_minimal_genesis_receipt_is_accepted",
    "test_retirement_installer_recovery.ReceiptTests.test_no_resume_total_loss_or_ex_claim_is_accepted",
    "test_retirement_installer_recovery.ReceiptTests.test_non_genesis_or_incomplete_state_never_passes",
    "test_retirement_operator.AbsenceTests.test_missing_requires_exact_no_such_name_and_empty_output",
    "test_retirement_operator.AbsenceTests.test_newline_absence_still_requires_exact_error_and_status",
    "test_retirement_operator.BinaryPipeTests.test_capacity_header_truncation_trailing_and_nonzero_stay_red",
    "test_retirement_operator.BinaryPipeTests.test_only_tar_bytes_reach_encryption_sink",
    "test_retirement_operator.BinaryPipeTests.test_short_sink_write_is_never_success",
    "test_retirement_operator.Capture129Guards.test_explicit_account_original_reaches_128_plus_one_without_omission",
    "test_retirement_operator.Capture129Guards.test_producer_default_never_opens_database_or_writes_manifest",
    "test_retirement_operator.InstalledControllerTests.test_actual_process_order_and_capture_before_guard_release",
    "test_retirement_operator.InstalledControllerTests.test_every_failure_cleans_before_guard_exit_without_next_stage",
    "test_retirement_operator.InstalledControllerTests.test_real_SIGTERM_finishes_owned_cleanup_before_guard_release",
    "test_retirement_operator.InstalledControllerTests.test_uncertain_cleanup_cannot_emit_receipt_or_enter_capture",
    "test_retirement_operator.InstalledPublisherRoundtrip.test_actual_generated_profile_reaches_launch_only_after_host_source_pin",
    "test_retirement_operator.InstalledPublisherRoundtrip.test_legacy_missing_pin_and_unknown_fields_are_closed",
    "test_retirement_operator.InstallerProcessTests.test_initializer_and_setter_removal_are_required_admission_events",
    "test_retirement_operator.InstallerProcessTests.test_no_signer_or_setter_before_required_process_absence",
    "test_retirement_operator.InstallerProcessTests.test_start_failure_still_attempts_exact_owned_removal",
    "test_retirement_operator.InstallerProcessTests.test_uncertain_initializer_or_setter_removal_keeps_signer_closed",
    "test_retirement_operator.NormalRuntimeGuards.test_closed_mode_scope_tokens_manifest_and_mass_assignment",
    "test_retirement_operator.NormalRuntimeGuards.test_default_normal_probe_starts_no_process",
    "test_retirement_operator.NormalRuntimeGuards.test_exact_compiled_bytes_reject_extra_missing_and_changed_runtime",
    "test_retirement_operator.NormalRuntimeGuards.test_exact_production_topology_argv_without_injection",
    "test_retirement_operator.NormalRuntimeGuards.test_flag_off_request_passes_closed_DTO_before_service_gate",
    "test_retirement_operator.PreparationTests.test_all_explicit_operators_default_to_no_private_actions",
    "test_retirement_operator.PreparationTests.test_publisher_never_accepts_an_unpinned_runtime",
    "test_retirement_operator.RecoveryHandoffGuards.test_attestation_is_removed_before_only_physical_EX_is_released",
    "test_retirement_operator.RecoveryHandoffGuards.test_changed_or_unremovable_attestation_keeps_physical_claim",
    "test_retirement_operator.RecoveryHandoffGuards.test_no_publisher_claim_or_repeated_handoff_cannot_release_anything",
    "test_retirement_operator.RecoveryHandoffGuards.test_total_host_recovery_remains_unconditionally_closed",
    "test_retirement_operator.ResourceIdentityGuards.test_known_renamed_ID_cannot_be_claimed_clean_or_blindly_removed",
    "test_retirement_operator.ResourceIdentityGuards.test_lost_create_can_resolve_only_matching_actual_owned_name",
    "test_retirement_operator.ResourceIdentityGuards.test_original_ID_and_exact_name_must_both_be_absent",
    "test_retirement_operator.ResourceIdentityGuards.test_returned_ID_retained_before_first_inspection_in_every_operator",
    "test_retirement_operator.ResourceIdentityGuards.test_same_name_labels_but_foreign_ID_cannot_replace_known_object",
    "test_retirement_operator.ResourceIdentityGuards.test_unresolved_lost_create_absence_remains_red",
    "test_retirement_provisioning.ProvisioningGuards.test_default_commands_read_no_inputs_and_cannot_clear_flags",
    "test_retirement_provisioning.ProvisioningGuards.test_excess_missing_capability_or_unconfirmed_readback_never_admit_signer",
    "test_retirement_provisioning.ProvisioningGuards.test_existing_flag_hardlink_changed_inode_and_wrong_owner_are_rejected",
    "test_retirement_provisioning.ProvisioningGuards.test_flag_is_one_way_readonly_descriptor_and_preserves_other_inode_flags",
    "test_retirement_scope.ScopeGuards.test_QA_never_reads_actual_crontab_and_cannot_use_other_run_schedule",
    "test_retirement_scope.ScopeGuards.test_QA_root_must_be_canonical_owner1000_private700",
    "test_retirement_scope.ScopeGuards.test_capture_and_recovery_all_QA_host_mounts_socket_owned",
    "test_retirement_scope.ScopeGuards.test_explicit_empty_QA_cli_rejected_before_private_actions",
    "test_retirement_scope.ScopeGuards.test_materializer_QA_host_bind_keeps_fixed_container_path_and_caps",
    "test_retirement_scope.ScopeGuards.test_only_closed_run_nonce_scope_is_accepted",
    "test_retirement_scope.ScopeGuards.test_production_cannot_infer_QA_from_ambient_environment",
    "test_retirement_scope.ScopeGuards.test_stopped_QA_checks_actual_owned_ID_labels_and_state",
    "test_retirement_singleton.SingletonMappingGuards.test_actual_launcher_inode_is_the_maintenance_inode",
)


def identities(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from identities(item)
        else:
            yield item.id()


def checked_suite(suite):
    if sorted(identities(suite)) != list(EXPECTED_IDS) or suite.countTestCases() != 77:
        raise RuntimeError("operator_exact77_collection_changed")
    return suite


def main() -> int:
    if sys.argv[1:] or sys.platform != "linux" or os.geteuid() != 1000:
        raise RuntimeError("operator_native_closed_UID1000_required")
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
    passed = result.wasSuccessful() and not result.skipped and result.testsRun == 77
    print(json.dumps({"status": "passed" if passed else "failed", **counts}))
    return int(not passed)


if __name__ == "__main__":
    raise SystemExit(main())
