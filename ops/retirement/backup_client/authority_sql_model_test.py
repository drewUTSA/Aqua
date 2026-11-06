"""Keyless signed event/SQL-result attack models; no actual database or Docker."""

from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import psycopg

sys.path.insert(0, str(Path(__file__).parent / "sql-verifier"))


def source_modules():
    from retirement.checkpoint import DOMAIN, payload
    from retirement.pages import INITIAL
    from verifier_checks import helpers
    from verifier_process import Failure
    import verifier_validation

    return DOMAIN, payload, INITIAL, helpers, Failure, verifier_validation


DOMAIN, payload, INITIAL, helpers, Failure, validation = source_modules()


def fixture(count=0):
    from retirement.fingerprints import Fingerprint
    from retirement.pages import encode, manifest, page_digest

    install = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    key = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    owner = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    intent = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    job = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    moment = datetime(2026, 11, 5, tzinfo=timezone.utc)
    original = manifest(
        encode("a" * 64, Fingerprint(key, "mailbox", index.to_bytes(32, "big")))
        for index in range(count)
    )
    scope, closed, auth = (
        ("account_v1", True, 1) if count else ("chat_history_v1", False, 0)
    )
    check_event, _ = helpers()
    Intent = check_event.__globals__["Intent"]
    record = Intent(
        install,
        owner,
        intent,
        job,
        scope,
        moment,
        2,
        2,
        auth,
        closed,
        1,
        bytes(32),
        moment,
        count,
        original.root,
    )
    digest = check_event.__globals__["event_digest"](record, bytes(32))
    signer = Ed25519PrivateKey.from_private_bytes(b"s" * 32)  # Public model seed.

    def signed(sequence, event, previous):
        raw = payload(install, key, sequence, event, previous, b"c" * 32)
        return raw + signer.sign(DOMAIN + raw)

    genesis = signed(0, bytes(32), bytes(32))
    head = signed(1, digest, hashlib.sha256(genesis).digest())
    chain = genesis + head
    expected = {
        "installation_id": install,
        "identity_key_id": key,
        "key_commitment": (b"c" * 32).hex(),
        "public_key": signer.public_key().public_bytes_raw().hex(),
        "head_hex": head.hex(),
        "protected_chain_sha256": hashlib.sha256(chain).hexdigest(),
    }
    event = (
        1,
        bytes(32),
        digest,
        intent,
        owner,
        job,
        moment,
        moment,
        moment,
        "sealed",
        scope,
        2,
        2,
        auth,
        closed,
        count,
        original.root,
    )
    control = (
        install,
        key,
        b"c" * 32,
        2,
        digest,
        1,
        digest,
        1,
        1,
        count,
        0,
        0,
        512 + count * 256,
    )
    pages, previous = [], INITIAL
    for ordinal, entries in enumerate(original.pages):
        current = page_digest(previous, ordinal, entries)
        pages.append((ordinal, previous, current, list(entries)))
        previous = current
    return expected, chain, event, control, pages


class Connection:
    def __init__(self, control, fault=None, count=0):
        self.control, self.fault, self.count = control, fault, count

    @contextmanager
    def transaction(self):
        yield

    def execute(self, sql, params=()):
        if sql == "SET TRANSACTION READ WRITE":
            row = None
        elif "rolconnlimit" in sql:
            row = (
                "aqua_retirement",
                "aqua_retirement_backup",
                "aqua_retirement_backup",
                False,
                False,
                False,
                False,
                False,
                False,
                1,
            )
        elif sql.startswith("SHOW "):
            row = ("on",)
        elif "has_database_privilege" in sql:
            row = (False, False, False, 4)
        elif "c.relkind" in sql:
            return SimpleNamespace(
                fetchall=lambda: [(name,) for name in sorted(validation.TABLES)]
            )
        elif "has_table_privilege" in sql:
            row = (True, self.fault == "privilege")
        elif sql.startswith(
            ("CREATE ", "SET ROLE", "TRUNCATE ", "UPDATE ", "DELETE ", "INSERT ")
        ):
            raise psycopg.errors.InsufficientPrivilege("public model denial")
        elif sql == validation.OWNER_FLOORS:
            row = (int(self.fault == "owner_floor"),)
        elif sql == validation.FINGERPRINTS:
            row = (int(self.fault == "fingerprint"),)
        elif sql.startswith("SELECT count(*) FROM retirement."):
            name = sql.rsplit(".", 1)[1]
            row = (
                {
                    "control": 1,
                    "owners": 1,
                    "intents": 1,
                    "pages": (self.count + 127) // 128,
                    "fingerprints": self.count,
                    "journal": 1,
                }[name],
            )
        elif sql.startswith("SELECT installation_id::text"):
            row = self.control
        elif "sum(512+expected_count" in sql:
            row = (512 + self.count * 256, int(self.fault == "manifest"))
        else:
            raise AssertionError("unmodeled_source_query")
        return SimpleNamespace(fetchone=lambda: row)


class Recovery:
    def __init__(self, event, fault=None, pages=()):
        self.event, self.fault, self.pages = event, fault, pages

    def execute(self, sql, params):
        if "read_events" in sql:
            rows = [self.event] if params[0] == 0 else []
        elif "read_pages" in sql:
            rows = (
                [p for p in self.pages if p[0] > params[1]][:4]
                if self.fault != "page"
                else [(0, INITIAL, b"f" * 32, [b"x" * 114])]
            )
        else:
            raise AssertionError("unmodeled_recovery_query")
        return SimpleNamespace(fetchall=lambda: rows)


class AuthorityModels(unittest.TestCase):
    def setUp(self):
        self.expected, self.chain, self.event, self.control, _ = fixture()

    def test_original_account_manifest_crosses_128_entry_page_boundary(self):
        expected, chain, event, control, pages = fixture(129)
        result = validation.validate(
            Connection(control, count=129),
            Recovery(event, pages=pages),
            chain,
            expected,
        )
        self.assertEqual(result["table_counts"]["pages"], 2)
        self.assertEqual(result["table_counts"]["fingerprints"], 129)

    def test_complete_signed_model_requires_all_six_tables_original_floors_and_pages(
        self,
    ):
        result = validation.validate(
            Connection(self.control), Recovery(self.event), self.chain, self.expected
        )
        self.assertEqual(result["events_verified"], 1)
        self.assertEqual(set(result["authority_tables"]), set(validation.TABLES))
        self.assertTrue(result["original_pages_and_floors_verified"])

    def test_signed_history_floor_cannot_be_reconstructed_to_another_value(self):
        changed = list(self.event)
        changed[11] = 3
        with self.assertRaises(Exception):
            validation.validate(
                Connection(self.control),
                Recovery(tuple(changed)),
                self.chain,
                self.expected,
            )

    def test_pending_unacknowledged_or_rewound_control_never_validates(self):
        for index, value in ((3, 1), (5, 0), (10, 1), (11, 1)):
            changed = list(self.control)
            changed[index] = value
            with self.subTest(index=index), self.assertRaises(Failure):
                validation.validate(
                    Connection(tuple(changed)),
                    Recovery(self.event),
                    self.chain,
                    self.expected,
                )

    def test_page_owner_floor_fingerprint_and_privilege_mutations_fail(self):
        for fault in ("page", "owner_floor", "fingerprint", "manifest", "privilege"):
            with self.subTest(fault=fault), self.assertRaises(Exception):
                validation.validate(
                    Connection(self.control, fault),
                    Recovery(self.event, fault),
                    self.chain,
                    self.expected,
                )

    def test_truncated_or_tampered_public_chain_is_not_accepted(self):
        for chain in (self.chain[:-1], self.chain[:-1] + bytes([self.chain[-1] ^ 1])):
            with self.assertRaises(Failure):
                validation.validate(
                    Connection(self.control), Recovery(self.event), chain, self.expected
                )


FATAL = 'FATAL:  too many connections for role "aqua_retirement_backup"'

PREFIX = 'connection failed: connection to server on socket "/run/aqua-app-db/.s.PGSQL.5432" failed: '


class FakeConnection:
    def __init__(self):
        self.closed = True
        self.queries = []

    def __enter__(self):
        self.closed = False
        return self

    def __exit__(self, *_):
        self.closed = True

    def execute(self, query):
        self.queries.append(query)
        return self

    def fetchone(self):
        return ("aqua_retirement_backup", "aqua_retirement_backup", 1)


def probe_module():
    import verifier_probe

    return verifier_probe


probe = probe_module()


class RoleCapTests(unittest.TestCase):
    def test_keeps_53300_and_accepts_only_fixed_operational_startup_limit(self):
        self.assertEqual(
            probe.denied_second_slot(psycopg.errors.TooManyConnections("synthetic")),
            "sqlstate_53300",
        )
        for text in [FATAL, FATAL + "\n", PREFIX + FATAL, PREFIX + FATAL + "\n"]:
            error = psycopg.OperationalError(text)
            self.assertIsNone(error.sqlstate)
            self.assertEqual(
                probe.denied_second_slot(error), "libpq_startup_exact_role_limit"
            )

    def test_rejects_wrong_role_password_endpoint_generic_extra_and_oversize(self):
        for text in [
            FATAL.replace("aqua_retirement_backup", "aqua_retirement_recovery"),
            'FATAL:  password authentication failed for user "aqua_retirement_backup"',
            "connection refused",
            "generic OperationalError",
            "untrusted sentinel\n" + FATAL,
            FATAL + "\nuntrusted sentinel",
            PREFIX.replace("aqua-app-db", "other-socket") + FATAL,
            " " * 1025 + FATAL,
        ]:
            with self.subTest(text_hash=hashlib.sha256(text.encode()).hexdigest()):
                with self.assertRaisesRegex(
                    Failure, "^verifier_backup_second_slot_not_proven$"
                ):
                    probe.denied_second_slot(psycopg.OperationalError(text))
        with self.assertRaises(Failure):
            probe.denied_second_slot(psycopg.Error(FATAL))

    def run_main(self, *, bad_control=False):
        first, recovery, control = FakeConnection(), FakeConnection(), FakeConnection()
        calls = []

        def connection(role):
            calls.append(role)
            if len(calls) == 1:
                return first
            if len(calls) == 2:
                return recovery
            if len(calls) == 3:
                self.assertFalse(first.closed)
                self.assertEqual(len(first.queries), 1)
                self.assertIn("rolconnlimit", first.queries[0])
                raise psycopg.OperationalError(PREFIX + FATAL + "\n")
            self.assertEqual(len(calls), 4)
            self.assertTrue(first.closed)
            self.assertTrue(recovery.closed)
            if bad_control:
                raise psycopg.OperationalError("untrusted control failure sentinel")
            return control

        def validate(backup, restored, chain, expected, *, diagnostic):
            self.assertIs(backup, first)
            self.assertIs(restored, recovery)
            self.assertFalse(first.closed)
            self.assertFalse(recovery.closed)
            diagnostic("accounting")
            return {"original_pages_and_floors_verified": True}

        def read(path):
            if path.name == "public.json":
                return json.dumps(
                    {"expected": {"head_hex": "00" * 208}, "dump_sha256": "d" * 64}
                ).encode()
            self.assertEqual(path.name, "chain.bin")
            return b"modeled public chain"

        out = io.StringIO()
        with (
            patch.object(probe, "connection", side_effect=connection),
            patch.object(probe.signal, "alarm"),
            patch.object(probe.sys, "argv", ["verifier_probe.py", "10"]),
            patch.object(probe.Path, "read_bytes", read),
            patch.object(validation, "validate", side_effect=validate),
            redirect_stdout(out),
        ):
            if bad_control:
                with self.assertRaises(SystemExit):
                    probe.main()
            else:
                probe.main()
        self.assertEqual(calls, ["backup", "recovery", "backup", "backup"])
        self.assertTrue(first.closed)
        self.assertTrue(recovery.closed)
        self.assertTrue(control.closed)
        self.assertNotIn("sentinel", out.getvalue())
        return json.loads(out.getvalue())

    def test_first_authenticated_held_then_same_DSN_after_close_control(self):
        result = self.run_main()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(
            result["backup_role_denial_mechanism"], "libpq_startup_exact_role_limit"
        )
        self.assertIs(result["backup_role_first_authenticated"], True)
        self.assertIs(result["backup_role_post_release_control"], True)

    def test_failed_post_release_control_cannot_pass_or_expose_error(self):
        result = self.run_main(bad_control=True)
        self.assertEqual(
            result,
            {
                "status": "failed",
                "probe_subphase": "backup_slot",
                "probe_failure_code": "unclassified_failure",
            },
        )


if __name__ == "__main__":
    unittest.main()
