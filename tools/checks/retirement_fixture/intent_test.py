"""Pure intent-tombstone behavior; actual SQL/restore constraints remain unrun."""

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
from retirement.intents import Intent, IntentConflict, replay, reconcile_tombstone
from retirement.pages import INITIAL

INSTALL = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OWNER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
INTENT = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
JOB = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
CREATED = datetime(2026, 10, 30, tzinfo=timezone.utc)
CHECKPOINTED = datetime(2026, 10, 31, tzinfo=timezone.utc)


class IntentTests(unittest.TestCase):
    def setUp(self):
        self.known = Intent(
            INSTALL,
            OWNER,
            INTENT,
            JOB,
            "chat_history_v1",
            CREATED,
            2,
            7,
            3,
            False,
            1,
            b"d" * 32,
            CHECKPOINTED,
        )
        self.args = dict(
            installation=INSTALL, owner=OWNER, intent=INTENT, scope="chat_history_v1"
        )

    def test_expired_visible_job_never_retires_new_history_under_old_intent(self):
        for current_generation in (2, 9, 9007199254740991):
            result = replay(self.known, **self.args)
            self.assertEqual(result.history_floor, 2)
            self.assertEqual(result.action, "replay_pending")
            self.assertFalse(result.cleanup_complete)
            self.assertEqual(result.job, JOB)
            self.assertEqual(result.created_at, CREATED)
            self.assertEqual(result.updated_at, CREATED)
            self.assertTrue(result.acceptance_confirmed)
            self.assertGreaterEqual(current_generation, result.history_floor)

    def test_foreign_or_changed_scope_and_missing_authority_cannot_create(self):
        for changes in (
            {"owner": INSTALL},
            {"intent": OWNER},
            {"scope": "account_v1"},
            {"installation": OWNER},
        ):
            with self.subTest(changes=changes), self.assertRaises(IntentConflict):
                replay(self.known, **{**self.args, **changes})
        with self.assertRaises(IntentConflict):
            replay(None, **self.args)

    def test_recovery_inserts_only_missing_metadata_and_reads_immutable_values(self):
        values = (
            INSTALL,
            OWNER,
            INTENT,
            JOB,
            "chat_history_v1",
            CREATED,
            2,
            7,
            3,
            False,
            0,
            INITIAL,
            1,
            b"d" * 32,
            CHECKPOINTED,
        )
        conn = Mock()
        conn.execute.return_value = SimpleNamespace(fetchone=lambda: values)
        result = reconcile_tombstone(conn, self.known)
        sql = conn.execute.call_args_list[0].args[0]
        self.assertIn("DO NOTHING", sql)
        self.assertNotIn("DO UPDATE", sql)
        self.assertFalse(result.cleanup_complete)

    def test_substituted_app_tombstone_fails_instead_of_updating_it(self):
        conn = Mock()
        conn.execute.return_value = SimpleNamespace(fetchone=lambda: None)
        with self.assertRaises(IntentConflict):
            reconcile_tombstone(conn, self.known)
        with self.assertRaises(IntentConflict):
            replace(self.known, history_floor=True)
        with self.assertRaises(IntentConflict):
            replace(self.known, scope="account_v1", closed=False)
        for changes in (
            {"history_floor": 1},
            {"privacy_floor": 1},
            {"scope": "account_v1", "closed": True, "auth_floor": 0},
        ):
            with self.subTest(changes=changes), self.assertRaises(IntentConflict):
                replace(self.known, **changes)

    def test_pending_replay_retains_original_phase_and_timestamp(self):
        pending = replace(
            self.known, sequence=None, event_digest=None, checkpointed_at=None
        )
        with self.assertRaises(IntentConflict):
            replay(pending, **self.args)
        result = replay(self.known, **self.args)
        self.assertEqual(result.action, "replay_pending")
        self.assertEqual(result.updated_at, CREATED)
        self.assertEqual(result.job, JOB)
        self.assertFalse(result.cleanup_complete)
        for change in ({"job": None}, {"created_at": None}, {"checkpointed_at": None}):
            with self.assertRaises((IntentConflict, ValueError, TypeError)):
                replace(self.known, **change)


if __name__ == "__main__":
    unittest.main()
