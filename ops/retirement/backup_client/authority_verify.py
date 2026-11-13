"""Cryptographic archive plus source-bound SQL verifier composition."""

from dataclasses import replace
import json

from authority_support import TABLES, archive, require, sha, stream


def verify_ram(raw, expected, restore_verify, seconds):
    """A separate trusted head and required actual SQL challenge bind recovery."""
    expected.checked()
    require(callable(restore_verify), "actual_dump_restore_verifier_required")
    bundle = archive.read(raw, bytes.fromhex(expected.head_hex))
    require(
        type(bundle.profile.get("schemaVersion")) is int,
        "authority_archive_schema_invalid",
    )
    require(
        all(
            bundle.profile.get(name) == getattr(expected, name)
            for name in (
                "installation_id",
                "identity_key_id",
                "key_commitment",
                "public_key",
                "runtime_image",
                "source_sha256",
            )
        ),
        "authority_archive_profile_mismatch",
    )
    chain = bundle.contents["checkpoints.bin"]
    require(
        sha(chain) == expected.protected_chain_sha256, "authority_full_chain_mismatch"
    )
    dump = bundle.contents["authority.dump"]
    # Only dump and public pins reach the restore controller, never the keys.
    try:
        verified = restore_verify(
            dump, replace(expected, verification_chain=chain), seconds
        )
    except Exception:
        raise stream.BackupError("authority_restore_verifier_failed") from None
    required = {
        "dump_sha256": sha(dump),
        "head_sha256": sha(bytes.fromhex(expected.head_hex)),
        "runtime_image": expected.runtime_image,
        "source_sha256": expected.source_sha256,
        "verifier_source_sha256": expected.restore_verifier_sha256,
    }
    require(
        type(verified) is dict
        and all(verified.get(k) == v for k, v in required.items()),
        "dump_restore_binding_invalid",
    )
    require(
        verified.get("status") == "passed"
        and verified.get("mode") in {"actual_disposable_restore", "synthetic_model"}
        and set(verified.get("authority_tables", [])) == TABLES
        and verified.get("original_pages_and_floors_verified") is True
        and verified.get("cleanup") == "removed_and_absence_confirmed"
        and verified.get("remaining_ids") == [],
        "full_dump_restore_not_verified",
    )
    if verified["mode"] == "actual_disposable_restore":
        from authority_sql_adapter import NativeSQLAdapter

        require(
            type(restore_verify) is NativeSQLAdapter,
            "actual_source_bound_adapter_required",
        )
    return {
        "plaintext_bytes": len(raw),
        "plaintext_sha256": sha(raw),
        "dump_sha256": sha(dump),
        "head_sha256": required["head_sha256"],
        "protected_chain_sha256": sha(chain),
        "full_chain_and_both_keys_verified": True,
        "sql_verifier_mode": verified["mode"],
        "sql_verifier_receipt_sha256": sha(
            json.dumps(verified, sort_keys=True, separators=(",", ":")).encode()
        ),
        "total_host_restore_supported": False,
    }
