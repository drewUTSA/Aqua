"""Offline protocol sketch; no application imports, I/O, clocks or release claim."""

from dataclasses import dataclass, field
import unittest


@dataclass
class Authority:
    floors: dict[str, int] = field(default_factory=dict)
    closed: set[str] = field(default_factory=set)
    events: dict[str, tuple[str, int, bool]] = field(default_factory=dict)
    complete: bool = True

    def acknowledge(self, intent, owner, generation, close=False):
        if not self.complete:
            raise ValueError("retirement_authority_unavailable")
        event = (owner, generation, close)
        if intent in self.events and self.events[intent] != event:
            raise ValueError("retirement_event_substitution")
        self.floors[owner] = max(self.floors.get(owner, 1), generation)
        if close:
            self.closed.add(owner)
        self.events[intent] = event


@dataclass
class State:
    owner: str = "owner-a"
    generation: int = 1
    privacy_epoch: int = 1
    active: bool = True
    intent: str | None = None
    status: str | None = None
    physical: int = 0
    chunks: int = 0

    def accept(self, intent, close=False):
        if self.intent is not None:
            if self.intent != intent:
                raise ValueError("operation_busy")
            return
        if not self.active:
            raise ValueError("account_closed")
        self.intent, self.status = intent, "pending_retirement"
        self.generation += 1
        self.privacy_epoch += 1
        if close:
            self.active = False

    def acknowledged(self, authority):
        expected = (self.owner, self.generation, not self.active)
        if authority.events.get(self.intent) != expected:
            raise ValueError("durability_unconfirmed")
        if authority.floors.get(self.owner, 1) < self.generation:
            raise ValueError("retirement_floor_missing")
        self.status = "retired"

    def visible(self, row_generation):
        return self.active and row_generation == self.generation

    def late_write(self, captured_epoch, captured_generation):
        return (
            self.active
            and self.privacy_epoch == captured_epoch
            and self.generation == captured_generation
        )

    def finish(self):
        if self.status != "retired" or self.physical or self.chunks:
            raise ValueError("cleanup_unconfirmed")
        self.status = "complete"

    def restore_fence(self, authority):
        if not authority.complete:
            raise ValueError("maintenance_required")
        self.generation = max(self.generation, authority.floors.get(self.owner, 1))
        self.active = self.active and self.owner not in authority.closed
        self.privacy_epoch += 1
        self.chunks = 0


class ProtocolDraftTests(unittest.TestCase):
    def test_accept_hides_old_history_but_new_generation_remains_visible(self):
        s = State()
        s.accept("intent-a")
        self.assertFalse(s.visible(1))
        self.assertTrue(s.visible(2))

    def test_same_intent_replay_does_not_increment_fences(self):
        s = State()
        s.accept("intent-a")
        s.accept("intent-a")
        self.assertEqual((s.generation, s.privacy_epoch), (2, 2))
        with self.assertRaises(ValueError):
            s.accept("intent-b")

    def test_local_commit_alone_cannot_acknowledge_retirement(self):
        s = State()
        s.accept("intent-a")
        with self.assertRaises(ValueError):
            s.acknowledged(Authority())
        with self.assertRaises(ValueError):
            s.finish()

    def test_event_ack_without_exact_owner_floor_is_insufficient(self):
        s = State()
        s.accept("intent-a")
        a = Authority(events={"intent-a": (s.owner, s.generation, False)})
        with self.assertRaises(ValueError):
            s.acknowledged(a)

    def test_late_analysis_and_export_cannot_publish_after_acceptance(self):
        s = State()
        epoch, generation = s.privacy_epoch, s.generation
        s.accept("intent-a")
        self.assertFalse(s.late_write(epoch, generation))

    def test_physical_owner_and_chunk_absence_are_needed_for_completion(self):
        s, a = State(physical=1, chunks=1), Authority()
        s.accept("intent-a")
        a.acknowledge("intent-a", s.owner, s.generation)
        s.acknowledged(a)
        with self.assertRaises(ValueError):
            s.finish()
        s.physical = 0
        with self.assertRaises(ValueError):
            s.finish()
        s.chunks = 0
        s.finish()
        self.assertEqual(s.status, "complete")

    def test_old_backup_history_is_hidden_by_independent_floor(self):
        a = Authority()
        a.acknowledge("intent-a", "owner-a", 2)
        restored = State(chunks=3)
        restored.restore_fence(a)
        self.assertFalse(restored.visible(1))
        self.assertEqual((restored.generation, restored.chunks), (2, 0))

    def test_old_backup_cannot_reenable_closed_account(self):
        a = Authority()
        a.acknowledge("intent-a", "owner-a", 2, close=True)
        restored = State()
        restored.restore_fence(a)
        self.assertFalse(restored.active)
        self.assertFalse(restored.visible(2))

    def test_missing_independent_retirement_authority_keeps_maintenance(self):
        with self.assertRaises(ValueError):
            State().restore_fence(Authority(complete=False))

    def test_new_uuid_does_not_inherit_old_owner_history_or_closure(self):
        a = Authority()
        a.acknowledge("intent-a", "owner-a", 2, close=True)
        new = State(owner="new-owner-uuid")
        new.restore_fence(a)
        self.assertTrue(new.active)
        self.assertEqual(new.generation, 1)
        self.assertFalse(new.visible(2))

    def test_retirement_floor_is_monotonic_under_duplicate_old_events(self):
        a = Authority()
        a.acknowledge("intent-new", "owner-a", 7)
        a.acknowledge("intent-old", "owner-a", 2)
        self.assertEqual(a.floors["owner-a"], 7)

    def test_durable_event_id_cannot_be_reused_for_another_owner_or_scope(self):
        a = Authority()
        a.acknowledge("intent-a", "owner-a", 2)
        for owner, generation, close in (
            ("owner-b", 2, False),
            ("owner-a", 3, False),
            ("owner-a", 2, True),
        ):
            with self.assertRaises(ValueError):
                a.acknowledge("intent-a", owner, generation, close)


if __name__ == "__main__":
    unittest.main()
