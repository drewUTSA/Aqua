"""Modeled physical ordering only; real-PG durability/restore remain unrun."""

from contextlib import contextmanager
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
from retirement.fingerprints import IdentityKey, ISSUER
from retirement.interlock import Broker, PHYSICAL, RetirementUnavailable
from retirement.checkpoint import CheckpointUnavailable, ProtectedFile

INSTALLATION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
KEY = IdentityKey(INSTALLATION, b"synthetic-key".ljust(32, b"0"))


class Connection:
    autocommit = True

    def __init__(self, events):
        self.events, self.dead, self.closed, self.locked = events, False, False, False
        self.info = SimpleNamespace(transaction_status=0)
        self.fail_commit = False

    @contextmanager
    def transaction(self):
        if self.info.transaction_status != 0:
            raise AssertionError("unexpected_nested_transaction")
        self.info.transaction_status = 2
        try:
            yield
            if self.fail_commit:
                raise RuntimeError("synthetic_commit_failure")
        finally:
            self.info.transaction_status = 0

    def execute(self, sql, arguments=None):
        if self.dead:
            raise RuntimeError("synthetic_database_session_lost")
        if "pg_try_advisory_lock" in sql:
            self.locked = True
            value = (True,)
            self.events.append("database_gate_acquired")
        elif "pg_advisory_unlock" in sql:
            self.locked = False
            value = (True,)
            self.events.append("database_gate_released")
        elif "pg_locks" in sql:
            value = (0,)
        elif "check_google_grant" in sql:
            value = (INSTALLATION, False)
            self.events.append("fresh_authority_read")
        elif "identity_context" in sql:
            value = (INSTALLATION, KEY.key_id, KEY.commitment)
        elif "synchronous_commit='on'" in sql:
            self.events.append("final_sync_on")
            value = None
        else:
            value = None
        return SimpleNamespace(fetchone=lambda: value)

    def close(self):
        self.closed = True
        self.events.append("dead_database_session_closed")


class Pool:
    def __init__(self, events):
        self.conn = Connection(events)

    @contextmanager
    def connection(self, *, timeout):
        assert timeout == 1.0
        yield self.conn


class InterlockTests(unittest.TestCase):
    def setUp(self):
        self.assertFalse(PHYSICAL.locked())
        self.events = []
        self.pool = Pool(self.events)
        # Explicit modeled checkpoint seam: no filesystem or nonrewind claim.
        self.checkpoint = object.__new__(ProtectedFile)
        self.checkpoint.require_current = lambda conn, **kwargs: None
        self.broker = Broker(
            self.pool, INSTALLATION, key=KEY, checkpoint=self.checkpoint
        )
        key = IdentityKey(INSTALLATION, b"synthetic-key".ljust(32, b"0"))
        self.candidates = key.google_grant_candidates(ISSUER, "Sub", "a@example.test")

    def tearDown(self):
        self.assertFalse(PHYSICAL.locked())

    def test_application_commit_and_cleanup_precede_physical_release(self):
        @contextmanager
        def transaction():
            self.events.append("app_transaction_open")
            self.assertTrue(PHYSICAL.locked())
            yield object()
            self.assertTrue(PHYSICAL.locked())
            self.events.append("app_commit_and_cleanup")

        result = self.broker.grant_transaction(
            SimpleNamespace(transaction=transaction),
            "dataset",
            self.candidates,
            lambda app, decision: decision.retired,
        )
        self.assertFalse(result)
        self.assertEqual(
            self.events,
            [
                "database_gate_acquired",
                "fresh_authority_read",
                "app_transaction_open",
                "app_commit_and_cleanup",
                "database_gate_released",
            ],
        )

    def test_lost_db_session_never_releases_claim_before_app_cleanup(self):
        draining, finish = threading.Event(), threading.Event()
        failures = []

        @contextmanager
        def transaction():
            try:
                yield object()
            finally:
                self.pool.conn.dead = True
                draining.set()
                if not finish.wait(5):
                    raise AssertionError("synthetic_app_drain_deadline")
                self.events.append("app_drained")

        def first():
            try:
                self.broker.grant_transaction(
                    SimpleNamespace(transaction=transaction),
                    "dataset",
                    self.candidates,
                    lambda app, decision: None,
                )
            except BaseException as error:
                failures.append(type(error))

        worker = threading.Thread(target=first)
        worker.start()
        try:
            self.assertTrue(draining.wait(2))
            other = Broker(
                Pool(self.events), INSTALLATION, key=KEY, checkpoint=self.checkpoint
            )
            with self.assertRaises(RetirementUnavailable):
                other.authority_transaction(lambda conn: self.fail("overlap admitted"))
            self.assertTrue(PHYSICAL.locked())
            self.assertFalse(self.pool.conn.closed)
        finally:
            finish.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [RetirementUnavailable])
        self.assertTrue(self.broker.poisoned)
        self.assertTrue(self.pool.conn.closed)
        self.assertLess(
            self.events.index("app_drained"),
            self.events.index("dead_database_session_closed"),
        )

    def test_unavailable_authority_does_not_enter_the_app_transaction(self):
        self.pool.conn.dead = True
        storage = SimpleNamespace(
            transaction=lambda: self.fail("app SQL before authority")
        )
        with self.assertRaises(RetirementUnavailable):
            self.broker.grant_transaction(storage, "dataset", self.candidates, None)

    def test_empty_or_substituted_fingerprints_cannot_query_or_mutate(self):
        storage = SimpleNamespace(
            transaction=lambda: self.fail("invalid input admitted")
        )
        for candidates in ((), tuple(reversed(self.candidates))):
            with self.assertRaises(RetirementUnavailable):
                self.broker.grant_transaction(storage, "dataset", candidates, None)
        self.assertNotIn("fresh_authority_read", self.events)

    def test_wrong_key_material_with_same_key_id_cannot_reach_app_SQL(self):
        wrong = IdentityKey(KEY.key_id, b"wrong-synthetic-key".ljust(32, b"0"))
        broker = Broker(self.pool, INSTALLATION, key=wrong, checkpoint=self.checkpoint)
        with self.assertRaises(RetirementUnavailable):
            broker.grant_transaction(
                SimpleNamespace(transaction=lambda: self.fail("wrong key admitted")),
                "dataset",
                self.candidates,
                None,
            )
        self.assertNotIn("fresh_authority_read", self.events)

    def test_checkpoint_loss_precedes_application_SQL(self):
        def deny(*args, **kwargs):
            raise CheckpointUnavailable()

        self.checkpoint.require_current = deny
        with self.assertRaises(RetirementUnavailable):
            self.broker.grant_transaction(
                SimpleNamespace(
                    transaction=lambda: self.fail("stale authority admitted")
                ),
                "dataset",
                self.candidates,
                None,
            )
        self.assertNotIn("fresh_authority_read", self.events)

    def test_owned_authority_transaction_forces_sync_after_callback(self):
        def apply(conn):
            self.events.append("callback_set_sync_off")
            conn.execute("SET LOCAL synchronous_commit='off'")
            return "pending_only"

        self.assertEqual(self.broker.authority_transaction(apply), "pending_only")
        self.assertLess(
            self.events.index("callback_set_sync_off"),
            self.events.index("final_sync_on"),
        )
        self.assertEqual(self.pool.conn.info.transaction_status, 0)

    def test_failed_commit_cannot_return_a_seal(self):
        def apply(conn):
            conn.fail_commit = True
            return "must_not_escape"

        with self.assertRaises(RetirementUnavailable):
            self.broker.authority_transaction(apply)
        self.assertTrue(self.pool.conn.closed)

    def test_callback_manual_commit_or_leftover_transaction_is_denied(self):
        def apply(conn):
            conn.info.transaction_status = 0
            return "must_not_escape"

        with self.assertRaises(RetirementUnavailable):
            self.broker.authority_transaction(apply)


if __name__ == "__main__":
    unittest.main()
