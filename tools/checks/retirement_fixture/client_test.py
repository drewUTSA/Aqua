"""Modeled typed-API boundaries only; no actual protected/SQL activation proof."""

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
import interlock_test as modeled
from retirement.checkpoint import CheckpointUnavailable, ProtectedFile
from retirement.client import (
    AuthorityClient,
    ConfirmedRetirement,
    PendingAuthority,
    ManifestSealed,
    ConfirmedAcceptance,
)
from retirement.intents import Intent
from retirement.interlock import Broker, PHYSICAL, RetirementUnavailable
from retirement.pages import INITIAL, Manifest, manifest

INSTALL = modeled.INSTALLATION
OWNER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
INTENT = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
JOB = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
CREATED = datetime(2026, 10, 30, tzinfo=timezone.utc)


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.assertFalse(PHYSICAL.locked())
        self.events = []
        self.pool = modeled.Pool(self.events)
        self.checkpoint = object.__new__(ProtectedFile)
        self.head = SimpleNamespace(sequence=1, event_digest=b"d" * 32)

        def current(conn, **kwargs):
            self.events.append("protected_current")
            return self.head

        self.checkpoint.require_current = current
        self.broker = Broker(
            self.pool, INSTALL, key=modeled.KEY, checkpoint=self.checkpoint
        )
        self.client = AuthorityClient(self.broker)
        self.record = Intent(
            INSTALL, OWNER, INTENT, JOB, "chat_history_v1", CREATED, 2, 2, 0, False
        )
        self.row = (
            INSTALL,
            INTENT,
            OWNER,
            JOB,
            CREATED,
            "chat_history_v1",
            2,
            2,
            0,
            False,
            0,
            0,
            INITIAL,
            "staging",
            0,
            INITIAL,
            1,
            b"d" * 32,
            None,
            None,
        )
        original = self.pool.conn.execute

        def execute(sql, arguments=None):
            if "lookup_intent" in sql:
                return SimpleNamespace(fetchone=lambda: self.row)
            if "seal_intent" in sql:
                return SimpleNamespace(fetchone=lambda: (1, b"d" * 32))
            if "append_page" in sql:
                return SimpleNamespace(fetchone=lambda: (b"p" * 32,))
            return original(sql, arguments)

        self.pool.conn.execute = execute

    def tearDown(self):
        self.assertFalse(PHYSICAL.locked())

    def test_known_intent_gate_and_original_metadata_remain_through_app_commit(self):
        @contextmanager
        def transaction():
            yield object()
            self.assertTrue(PHYSICAL.locked())
            self.assertTrue(self.pool.conn.locked)
            self.events.append("app_commit")

        def apply(app, known):
            self.assertEqual(known, self.record)
            return "old_job_only"

        value = self.client.intent_transaction(
            SimpleNamespace(transaction=transaction),
            OWNER,
            INTENT,
            "chat_history_v1",
            apply,
        )
        self.assertEqual(value.value, "old_job_only")
        self.assertFalse(value.acceptance_confirmed)
        self.assertLess(
            self.events.index("protected_current"), self.events.index("app_commit")
        )
        self.assertLess(
            self.events.index("app_commit"), self.events.index("database_gate_released")
        )

    def test_absence_or_foreign_intent_never_bypasses_current_checkpoint(self):
        self.row = None

        @contextmanager
        def transaction():
            yield object()

        self.assertIsNone(
            self.client.intent_transaction(
                SimpleNamespace(transaction=transaction),
                OWNER,
                INTENT,
                "chat_history_v1",
                lambda app, known: known,
            ).value
        )

        def missing(*args, **kwargs):
            raise CheckpointUnavailable()

        self.checkpoint.require_current = missing
        with self.assertRaises(RetirementUnavailable):
            self.client.intent_transaction(
                SimpleNamespace(
                    transaction=lambda: self.fail("app before protected proof")
                ),
                OWNER,
                INTENT,
                "chat_history_v1",
                None,
            )

    def test_confirm_requires_actual_ack_field_and_current_covering_head(self):
        with self.assertRaises(RetirementUnavailable):
            self.client.confirm_acceptance(OWNER, INTENT, "chat_history_v1")
        row = list(self.row)
        row[13], row[16], row[17] = "sealed", 1, b"d" * 32
        self.row = tuple(row)
        with self.assertRaises(RetirementUnavailable):
            self.client.confirm(OWNER, INTENT, "chat_history_v1")
        row[18] = CREATED + timedelta(seconds=1)
        row[19] = CREATED + timedelta(seconds=2)
        self.row = tuple(row)
        result = self.client.confirm(OWNER, INTENT, "chat_history_v1")
        self.assertIsInstance(result, ConfirmedRetirement)
        self.assertFalse(result.cleanup_complete)
        self.assertEqual(result.record.job, JOB)
        self.head.sequence = 0
        with self.assertRaises(RetirementUnavailable):
            self.client.confirm(OWNER, INTENT, "chat_history_v1")

    def test_raw_seal_is_only_pending_until_independent_confirm(self):
        value = self.client.seal(INTENT)
        self.assertIsInstance(value, ManifestSealed)
        self.assertFalse(value.purge_authorized)
        self.assertIn("final_sync_on", self.events)
        self.assertLess(
            self.events.index("final_sync_on"),
            self.events.index("database_gate_released"),
        )

    def test_manifest_is_finite_and_recomputed_before_any_DB_operation(self):
        for item in (
            Manifest(1, INITIAL, ()),
            Manifest(0, b"x" * 32, ()),
            Manifest(0, INITIAL, iter(())),
            Manifest(True, INITIAL, ()),
        ):
            with self.assertRaises(RetirementUnavailable):
                self.client.prepare(self.record, item)
        self.assertEqual(self.events, [])

    def test_header_checkpoint_acceptance_is_distinct_from_manifest_completion(self):
        self.assertIsInstance(
            self.client.prepare(self.record, manifest(())), PendingAuthority
        )
        row = list(self.row)
        row[18] = CREATED + timedelta(seconds=1)
        self.row = tuple(row)
        accepted = self.client.confirm_acceptance(OWNER, INTENT, "chat_history_v1")
        self.assertIsInstance(accepted, ConfirmedAcceptance)
        self.assertTrue(accepted.acceptance_confirmed)
        self.assertFalse(accepted.cleanup_complete)
        pending = self.client.confirm(OWNER, INTENT, "chat_history_v1")
        self.assertIsInstance(pending, PendingAuthority)
        self.assertTrue(pending.acceptance_confirmed)

    def test_local_commit_and_header_without_protected_ACK_cannot_acknowledge_HTTP(
        self,
    ):
        @contextmanager
        def transaction():
            yield object()

        self.row = None
        local = self.client.intent_transaction(
            SimpleNamespace(transaction=transaction),
            OWNER,
            INTENT,
            "chat_history_v1",
            lambda app, known: "committed_closed_locally",
        )
        self.assertFalse(local.acceptance_confirmed)
        with self.assertRaises(RetirementUnavailable):
            self.client.confirm_acceptance(OWNER, INTENT, "chat_history_v1")

    def test_original_job_or_owner_substitution_is_not_a_new_intent(self):
        with self.assertRaises(RetirementUnavailable):
            self.client.prepare(replace(self.record, job=OWNER), manifest(()))
        with self.assertRaises(RetirementUnavailable):
            self.client.confirm(JOB, INTENT, "chat_history_v1")
        with self.assertRaises(RetirementUnavailable):
            self.client.intent_transaction(
                SimpleNamespace(
                    transaction=lambda: self.fail("foreign intent admitted")
                ),
                JOB,
                INTENT,
                "chat_history_v1",
                None,
            )

    def test_append_shape_is_closed_before_IO(self):
        for ordinal, previous, entries in (
            (True, b"p" * 32, (b"x" * 114,)),
            (0, b"p", (b"x" * 114,)),
            (0, b"p" * 32, [b"x" * 114]),
            (0, b"p" * 32, (b"x" * 113,)),
        ):
            with self.assertRaises(RetirementUnavailable):
                self.client.append_page(INTENT, ordinal, previous, entries)
        self.assertEqual(self.events, [])


if __name__ == "__main__":
    unittest.main()
