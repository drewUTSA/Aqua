"""A real independent SQLite journal, using public deterministic fixture records."""

from concurrent.futures import ThreadPoolExecutor
import dataclasses
import hashlib
import json
from pathlib import Path
import sqlite3
import os
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.exceptions import InvalidSignature

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
from ops.recovery_witness.journal import (  # noqa: E402
    Identity,
    Witness,
    WitnessUnavailable,
)
from ops.recovery_witness.channel import respond  # noqa: E402
from retirement.publisher import service_request  # noqa: E402
from retirement.checkpoint import (  # noqa: E402
    DOMAIN,
    ZERO,
    CheckpointUnavailable,
    payload,
)


class WitnessTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name).resolve() / "checkpoint.sqlite3"
        # Published test-only fixture from ops/retirement/backup_client/authority_test_fixtures.py.
        self.key = Ed25519PrivateKey.from_private_bytes(b"s" * 32)
        self.identity = Identity(
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            b"k" * 32,
            self.key.public_key().public_bytes_raw(),
        )
        self.witness = Witness(self.path, self.identity)
        self.fence_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        self.genesis = self.record(0, ZERO, ZERO)
        self.first = self.record(1, b"a" * 32, hashlib.sha256(self.genesis).digest())
        self.second = self.record(2, b"b" * 32, hashlib.sha256(self.first).digest())

    def record(self, seq, digest, prev):
        frame = payload(
            self.identity.installation,
            self.identity.key_id,
            seq,
            digest,
            prev,
            self.identity.commitment,
        )
        return frame + self.key.sign(DOMAIN + frame)

    def test_absent_file_is_never_bootstrapped_on_append_or_fence(self):
        for action in (
            lambda: self.witness.append(1, self.genesis),
            lambda: self.witness.fence(1, self.fence_id),
        ):
            with self.assertRaises(FileNotFoundError):
                action()
            self.assertFalse(self.path.exists())
        with self.assertRaises(WitnessUnavailable):
            self.witness.enroll(self.first)
        self.assertFalse(self.path.exists())

    def test_enroll_is_exclusive_and_enrollment_identity_remains_bound(self):
        self.witness.enroll(self.genesis)
        with self.assertRaises(FileExistsError):
            self.witness.enroll(self.genesis)
        different = Witness(
            self.path, dataclasses.replace(self.identity, commitment=b"d" * 32)
        )
        with self.assertRaises(WitnessUnavailable):
            different.fence(1, self.fence_id)

    def test_gap_corruption_fork_and_stale_rejected(self):
        self.witness.enroll(self.genesis)
        for bad in (
            self.second,
            self.record(1, b"a" * 32, b"z" * 32),
            self.first[:-1],
            self.first[:-1] + bytes([self.first[-1] ^ 1]),
        ):
            with self.assertRaises((WitnessUnavailable, CheckpointUnavailable)):
                self.witness.append(1, bad)
        self.assertEqual(
            self.witness.append(1, self.first), hashlib.sha256(self.first).digest()
        )
        for bad in (
            self.genesis,
            self.record(1, b"c" * 32, hashlib.sha256(self.genesis).digest()),
        ):
            with self.assertRaises(WitnessUnavailable):
                self.witness.append(1, bad)
        self.assertEqual(self.witness.fence(1, self.fence_id).head, self.first)

    def test_racing_disagreeing_next_records_admits_one(self):
        self.witness.enroll(self.genesis)
        fork = self.record(1, b"c" * 32, hashlib.sha256(self.genesis).digest())

        def submit(record):
            try:
                return self.witness.append(1, record)
            except WitnessUnavailable:
                return None

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(submit, (fork, self.first)))
        self.assertEqual(results.count(None), 1)
        head = self.witness.fence(1, self.fence_id)
        self.assertIn(hashlib.sha256(head.head).digest(), results)

    def test_crash_after_durable_append_allows_exact_repeat_after_reopen(self):
        self.witness.enroll(self.genesis)
        committed = self.witness.append(1, self.first)
        reopened = Witness(self.path, self.identity)
        self.assertEqual(reopened.append(1, self.first), committed)
        self.assertEqual(reopened.fence(1, self.fence_id).sequence, 1)

    def test_stale_snapshot_fails_while_matching_one_remains_fenced(self):
        self.witness.enroll(self.genesis)
        self.witness.append(1, self.first)
        current = self.witness.fence(1, self.fence_id)
        for chain in (
            self.genesis,
            self.first + self.genesis,
            self.genesis + self.first + self.second,
        ):
            with self.assertRaises(WitnessUnavailable):
                with self.witness.recovery_cut(1, self.fence_id, chain):
                    self.fail("stale callback invoked")
        with self.witness.recovery_cut(
            1, self.fence_id, self.genesis + self.first
        ) as cut:
            self.assertEqual(cut, current)
        with self.assertRaises(WitnessUnavailable):
            self.witness.append(1, self.second)

    def test_failure_keeps_fence_and_old_writer_never_returns(self):
        self.witness.enroll(self.genesis)
        cut = self.witness.fence(1, self.fence_id)
        with self.assertRaises(RuntimeError):
            with self.witness.recovery_cut(1, self.fence_id, self.genesis):
                raise RuntimeError("interrupted")
        self.assertEqual(self.witness.frozen_head(1, self.fence_id), cut)
        with self.assertRaises(WitnessUnavailable):
            self.witness.release(dataclasses.replace(cut, chain_sha256="0" * 64))
        self.assertEqual(self.witness.release(cut), 2)
        with self.assertRaises(WitnessUnavailable):
            self.witness.append(1, self.first)
        self.witness.append(2, self.first)

    def test_missing_history_and_different_fence_never_yield_a_recovery_cut(self):
        self.witness.enroll(self.genesis)
        self.witness.append(1, self.first)
        self.witness.fence(1, self.fence_id)
        other = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
        with self.assertRaises(WitnessUnavailable):
            self.witness.fence(1, other)
        from contextlib import closing

        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("DELETE FROM records WHERE seq=0")
            conn.commit()
        with self.assertRaises(WitnessUnavailable):
            self.witness.frozen_head(1, self.fence_id)

    def service_keys(self):
        # Public fixtures, deliberately distinct from the checkpoint signing key.
        service = Ed25519PrivateKey.from_private_bytes(b"c" * 32)
        station = Ed25519PrivateKey.from_private_bytes(b"w" * 32)
        public = service.public_key().public_bytes_raw()
        self.witness.enroll(self.genesis, service_public_key=public)
        return service, station, public

    def test_signed_receipt_binds_fresh_challenge_and_both_keys(self):
        service, station, public = self.service_keys()
        request, verify = service_request(1, self.first, service, station.public_key())
        duplicate, check_duplicate = service_request(
            1, self.first, service, station.public_key()
        )
        self.assertNotEqual(duplicate, request)
        reply = respond(self.witness, 1, public, station, request)
        self.assertEqual(verify(reply), hashlib.sha256(self.first).digest())
        with self.assertRaises(InvalidSignature):
            check_duplicate(reply)
        alien, _ = service_request(1, self.first, station, station.public_key())
        with self.assertRaises(InvalidSignature):
            respond(self.witness, 1, public, station, alien)
        with self.assertRaises(InvalidSignature):
            respond(
                self.witness,
                1,
                public,
                station,
                request[:-1] + bytes([request[-1] ^ 1]),
            )
        _, check_other = service_request(1, self.first, service, service.public_key())
        with self.assertRaises(InvalidSignature):
            check_other(reply)
        with self.assertRaises(ValueError):
            respond(self.witness, 1, public, station, request + b"0")

    def test_old_credential_cannot_claim_new_generation_or_enroll_over_fence(self):
        service, station, public = self.service_keys()
        cut = self.witness.fence(1, self.fence_id)
        request, _ = service_request(1, self.first, service, station.public_key())
        with self.assertRaises(WitnessUnavailable):
            respond(self.witness, 1, public, station, request)
        with self.assertRaises(WitnessUnavailable):
            self.witness.release(cut)
        with self.assertRaises(sqlite3.IntegrityError):
            self.witness.release(cut, new_service_public_key=public)
        new = Ed25519PrivateKey.from_private_bytes(b"n" * 32)
        new_public = new.public_key().public_bytes_raw()
        self.assertEqual(
            self.witness.release(cut, new_service_public_key=new_public), 2
        )
        old, _ = service_request(2, self.first, service, station.public_key())
        with self.assertRaises(WitnessUnavailable):
            respond(self.witness, 2, public, station, old)
        with self.assertRaises(InvalidSignature):
            respond(self.witness, 2, new_public, station, old)
        current, verify = service_request(2, self.first, new, station.public_key())
        self.assertEqual(
            verify(respond(self.witness, 2, new_public, station, current)),
            hashlib.sha256(self.first).digest(),
        )

    def test_deleted_tail_cannot_silently_roll_back_current_head(self):
        self.witness.enroll(self.genesis)
        self.witness.append(1, self.first)
        from contextlib import closing

        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("DELETE FROM records WHERE seq=1")
            conn.commit()
        with self.assertRaises(WitnessUnavailable):
            self.witness.fence(1, self.fence_id)
        with self.assertRaises(WitnessUnavailable):
            self.witness.append(1, self.first)

    def test_pinned_host_installation_cannot_drop_or_switch_the_witness(self):
        from ops.retirement import retirement_host as host

        service, station, _ = self.service_keys()
        data = {
            "installation_id": self.identity.installation,
            "identity_key_id": self.identity.key_id,
            "key_commitment": self.identity.commitment.hex(),
            "public_key": self.identity.public_key.hex(),
            "checkpoint_dsn": "postgresql://aqua_retirement_checkpoint:"
            + ("q" * 43)
            + "@/aqua_retirement?host=/run/aqua-app-db&port=5432&sslmode=disable",
        }
        witness = {
            "generation": 1,
            "service_public_key": service.public_key().public_bytes_raw().hex(),
            "witness_public_key": station.public_key().public_bytes_raw().hex(),
        }
        settings = host.parse_settings(json.dumps(dict(data, witness=witness)).encode())
        pin = host.witness_profile_pin(settings)
        self.assertEqual(len(pin), 64)
        for wrong in (
            {"generation": 2},
            {"service_public_key": self.identity.public_key.hex()},
        ):
            if "service_public_key" in wrong:
                with self.assertRaises(host.HostUnavailable):
                    host.parse_settings(
                        json.dumps(dict(data, witness=dict(witness, **wrong))).encode()
                    )
            else:
                alternate = host.parse_settings(
                    json.dumps(dict(data, witness=dict(witness, **wrong))).encode()
                )
                self.assertNotEqual(pin, host.witness_profile_pin(alternate))
        if sys.platform.startswith("linux"):
            for body, expected in (
                (data, pin),
                (dict(data, witness=witness), None),
                (dict(data, witness=witness), "0" * 64),
            ):
                with (
                    patch.object(
                        host, "read_private", return_value=json.dumps(body).encode()
                    ),
                    patch.object(host, "signing_key") as signer,
                ):
                    with self.assertRaises(host.HostUnavailable):
                        host.execute(witness_pin=expected)
                    signer.assert_not_called()

    @unittest.skipUnless(sys.platform == "win32", "requires Windows CurrentUser DPAPI")
    def test_windows_witness_key_uses_separate_profile_and_pinned_public_key(self):
        from ops.recovery_witness.station import load_station_key

        # Encrypt the published fixture only. The test runs exclusively under its temp directory.
        station = Ed25519PrivateKey.from_private_bytes(b"w" * 32)
        base = self.path.parent / "Aqua" / "RecoveryIdentities"
        base.mkdir(parents=True)
        file = base / ("witness-" + self.identity.installation + ".dpapi")
        program = (
            "$ErrorActionPreference='Stop';$b=[byte[]](119)*32;"
            "$p=[Security.Cryptography.ProtectedData]::Protect($b,$null,"
            "[Security.Cryptography.DataProtectionScope]::CurrentUser);"
            "$s=[Console]::OpenStandardOutput();$s.Write($p,0,$p.Length);$s.Flush()"
        )
        ans = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", program],
            capture_output=True,
            timeout=10,
            check=True,
        )
        file.write_bytes(ans.stdout)
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.path.parent)}):
            selected = load_station_key(
                self.identity, station.public_key().public_bytes_raw()
            )
            challenge = b"Synthetic verification"
            station.public_key().verify(selected.sign(challenge), challenge)
            with self.assertRaises(ValueError):
                load_station_key(self.identity, self.identity.public_key)


if __name__ == "__main__":
    unittest.main()
