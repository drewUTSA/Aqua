"""Strict native-fixture controls; every accepted ACK comes from real SQL/Ed25519."""

import hashlib
import os
from pathlib import Path
import sys

AUTH_PASSWORD = "s" * 43  # Public fixture credential, never an installed secret.
SEED = bytes.fromhex("33" * 32)
INSTALLATION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
KEY_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
IDENTITY_BYTES = b"synthetic-fixture-HMAC-key-only!".ljust(32, b"0")
AUTHORITY = Path("/run/aqua-retirement")
FLAG = "AQUA_RETIREMENT_NATIVE_FIXTURE"


def enabled() -> bool:
    """A misspelled native request cannot quietly fall back to mocked storage."""
    value = os.environ.get(FLAG)
    if value not in {None, "true"}:
        raise RuntimeError("native_retirement_fixture_mode_invalid")
    return value == "true"


def sync(stage: str) -> None:
    """The controller may advance only this closed synthetic protocol."""
    if stage not in {"NATIVE_PUBLISH", "NATIVE_CRASH_BEFORE_ACK", "NATIVE_POISON"}:
        raise RuntimeError("native_retirement_fixture_stage_invalid")
    print(stage, flush=True)
    if sys.stdin.readline().strip() != "continue":
        raise RuntimeError("native_retirement_fixture_controller_missing")


def pending_receipt(before: dict, after: dict) -> None:
    """An uncommitted protected ACK cannot change the original receipt or purge."""
    for value in (before, after):
        if set(value) != {"schemaVersion", "user_id", "job", "history_revision"}:
            raise AssertionError("native_pending_receipt_shape_changed")
        job = value["job"]
        if set(job) != {
            "id",
            "intent_id",
            "scope",
            "state",
            "accepted",
            "cleanup_complete",
            "created_at",
            "receipt_expires_at",
        }:
            raise AssertionError("native_pending_job_shape_changed")
        if (
            job["state"] != "awaiting_authority"
            or job["accepted"] is not False
            or job["cleanup_complete"] is not False
        ):
            raise AssertionError("native_uncommitted_ACK_claimed_acceptance_or_cleanup")
    if before != after:
        raise AssertionError("native_original_pending_receipt_changed")


class Publisher:
    """Request a separately launched real publisher, never manufacture an ACK."""

    def __init__(self, protected):
        self.protected = protected

    def startup(self):
        return self.protected.head(full=True)

    def once(self):
        sync("NATIVE_PUBLISH")
        return self.protected.head(full=True)

    def crash_before_ack(self) -> str:
        sync("NATIVE_CRASH_BEFORE_ACK")
        return hashlib.sha256(self.protected.path.read_bytes()).hexdigest()
