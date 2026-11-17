"""Isolated encrypted capture proposal; default CLI performs no actions."""

import json
import os
from pathlib import Path
import re
import sys
import time

from authority_budget import checked as check_deadline
from authority_contract import (
    Expected as Expected,
    ExporterRoute,
    metadata,
    remote_command,
)
from authority_verify import verify_ram
from authority_support import (
    TABLES as TABLES,
    archive as archive,
    HOLDERS as HOLDERS,
    MAX_ARCHIVE,
    Operation,
    host,
    require,
    sha,
    stream,
)


class Transport:
    """Concrete pinned primitives, deliberately not wired to an executable CLI."""

    def __init__(self, *, route=None):
        require(
            route is None or type(route) is ExporterRoute,
            "authority_route_pins_required",
        )
        if route is not None:
            route.checked()
        self.route = route

    def _command(self, stage, action, expected):
        if self.route is None:
            return remote_command(stage, action, expected)
        return remote_command(stage, action, expected, route=self.route)

    def head(self, stage, expected, *, seconds=None):
        command = self._command(stage, "head", expected)
        raw = (
            stream.bounded_metadata(command)
            if seconds is None
            else stream.bounded_metadata(command, seconds=seconds)
        )
        return json.loads(raw)

    def encrypt(self, stage, expected, recipients, destination, seconds):
        return stream.encrypt_export(
            self._command(stage, "export", expected),
            recipients,
            destination,
            seconds=seconds,
            maximum=MAX_ARCHIVE,
        )

    def decrypt(self, ciphertext, identity, seconds):
        from authority_decrypt import decrypt_ram

        return decrypt_ram(ciphertext, identity, seconds=seconds)


def _collect(
    stage,
    directory,
    identity,
    recipients,
    expected,
    restore_verify,
    *,
    transport,
    deadline=None,
):
    """Capture only after caller supplies reviewed real helper and verifier APIs."""
    check_deadline(deadline)
    expected.checked()
    require(callable(restore_verify), "actual_dump_restore_verifier_required")
    require(
        1 <= len(recipients) <= 4
        and all(re.fullmatch(r"age1[0-9a-z]{55,90}", r) for r in recipients),
        "authority_recipients_invalid",
    )
    directory = Path(directory)
    project = host.PROJECT.resolve()
    require(
        directory != project and project not in directory.parents,
        "authority_backup_inside_resolved_checkout",
    )
    directory_pin = host.private_directory(directory)
    require(
        Path(identity).resolve() != host.SSH_IDENTITY.resolve(),
        "authority_ssh_identity_reuse_denied",
    )
    require(
        host.backup_recipient(identity) in recipients,
        "authority_local_recovery_recipient_missing",
    )
    check_deadline(deadline)

    def head():
        if deadline is None:
            return transport.head(stage, expected)
        return transport.head(stage, expected, seconds=deadline.seconds("head"))

    before = metadata(head(), expected)
    check_deadline(deadline)
    legacy_end = time.monotonic() + 300 if deadline is None else None

    def budget(operation):
        if deadline is not None:
            return deadline.seconds(operation)
        left = min(120, legacy_end - time.monotonic())
        require(left > 0, "authority_capture_deadline")
        return left

    pending = directory / (".pending-authority-" + os.urandom(12).hex() + ".age")
    final = None
    pending_identity = None
    try:
        encrypted = transport.encrypt(
            stage, expected, recipients, pending, budget("encrypt")
        )
        info = stream.private_file(pending, maximum=MAX_ARCHIVE + 1024**2)
        pending_identity = (info.st_dev, info.st_ino)
        check_deadline(deadline)
        cipher_digest = host.cipher_hash(pending)
        raw = transport.decrypt(pending, identity, budget("decrypt"))
        check_deadline(deadline)
        require(
            type(raw) is bytes and 0 < len(raw) <= MAX_ARCHIVE,
            "authority_decrypted_capacity",
        )
        require(
            encrypted == {"plaintext_bytes": len(raw), "plaintext_sha256": sha(raw)},
            "authority_authenticated_decryption_mismatch",
        )
        if deadline is None:
            result = verify_ram(raw, expected, restore_verify, budget("sql_restore"))
        else:
            result = verify_ram(raw, expected, restore_verify, 120, deadline=deadline)
        del raw
        require(
            metadata(head(), expected) == before,
            "authority_capture_head_changed",
        )
        require(
            host.private_directory(directory) == directory_pin
            and (deadline is not None or time.monotonic() <= legacy_end),
            "authority_directory_or_deadline_changed",
        )
        info = stream.private_file(pending, maximum=MAX_ARCHIVE + 1024**2)
        require(
            (info.st_dev, info.st_ino) == pending_identity
            and host.cipher_hash(pending) == cipher_digest,
            "authority_cipher_changed_during_verification",
        )
        check_deadline(deadline)
        final = directory / (
            "authority-"
            + expected.maintenance_nonce
            + "-"
            + os.urandom(8).hex()
            + ".tar.age"
        )
        os.link(pending, final, follow_symlinks=False)
        pending.unlink()
        info = stream.private_file(final, maximum=MAX_ARCHIVE + 1024**2)
        require(
            (info.st_dev, info.st_ino) == pending_identity
            and host.cipher_hash(final) == cipher_digest,
            "authority_published_cipher_changed",
        )
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        check_deadline(deadline)
        return {
            "status": (
                "verified_capture"
                if result["sql_verifier_mode"] == "actual_disposable_restore"
                else "modeled_only"
            ),
            **result,
            "encrypted_file": final.name,
            "encrypted_sha256": cipher_digest,
            "maintenance_nonce": expected.maintenance_nonce,
            "profile_sha256": expected.profile_sha256,
            "source_sha256": expected.source_sha256,
            "runtime_image": expected.runtime_image,
            "capture_point_authority_only": True,
            "globally_latest_accepted_head_proven": False,
            "independent_storage_proven": False,
            "plaintext_disk_files": 0,
        }
    except BaseException:
        # Only encrypt_export's exclusively created pending artifact is eligible.
        # Keep a published ciphertext if a later metadata-only operation fails.
        if pending.exists() and pending_identity is not None:
            info = stream.private_file(pending, maximum=MAX_ARCHIVE + 1024**2)
            require(
                (info.st_dev, info.st_ino) == pending_identity,
                "authority_cipher_cleanup_identity_changed",
            )
            pending.unlink()
        raise


def collect(
    stage,
    directory,
    identity,
    recipients,
    expected,
    restore_verify,
    *,
    transport,
    deadline=None,
):
    with Operation():
        return _collect(
            stage,
            directory,
            identity,
            recipients,
            expected,
            restore_verify,
            transport=transport,
            deadline=deadline,
        )


def _verify_recovered(
    ciphertext, identity, expected, capture, restore_verify, *, transport, deadline=None
):
    """Fetched-copy challenge; storage provenance is a separate reviewed gate."""
    check_deadline(deadline)
    require(
        host.cipher_hash(ciphertext) == capture.get("encrypted_sha256"),
        "authority_recovered_cipher_mismatch",
    )
    raw = transport.decrypt(
        ciphertext, identity, 120 if deadline is None else deadline.seconds("decrypt")
    )
    check_deadline(deadline)
    require(
        type(raw) is bytes
        and 0 < len(raw) <= MAX_ARCHIVE
        and sha(raw) == capture.get("plaintext_sha256"),
        "authority_recovered_plaintext_mismatch",
    )
    result = (
        verify_ram(raw, expected, restore_verify, 120)
        if deadline is None
        else verify_ram(raw, expected, restore_verify, 120, deadline=deadline)
    )
    require(
        host.cipher_hash(ciphertext) == capture.get("encrypted_sha256"),
        "authority_recovered_cipher_changed",
    )
    require(
        all(
            result.get(k) == capture.get(k)
            for k in ("head_sha256", "protected_chain_sha256", "dump_sha256")
        ),
        "authority_recovered_coverage_mismatch",
    )
    check_deadline(deadline)
    return {
        "status": (
            "verified_recovery"
            if result["sql_verifier_mode"] == "actual_disposable_restore"
            else "modeled_only"
        ),
        **result,
        "independent_storage_proven": False,
        "globally_latest_accepted_head_proven": False,
        "plaintext_disk_files": 0,
    }


def verify_recovered(
    ciphertext, identity, expected, capture, restore_verify, *, transport, deadline=None
):
    with Operation():
        return _verify_recovered(
            ciphertext,
            identity,
            expected,
            capture,
            restore_verify,
            transport=transport,
            deadline=deadline,
        )


def main():
    require(not sys.argv[1:], "authority_production_CLI_not_enabled")
    print(
        json.dumps(
            {
                "status": "prepared_only",
                "server_actions": 0,
                "private_key_reads": 0,
                "exports": 0,
                "writes": 0,
                "production_CLI_enabled": False,
                "total_host_restore_supported": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
