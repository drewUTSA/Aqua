"""Tampered recovery metadata cannot replace the protected event/manifest chain."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from retirement.checkpoint import ZERO
from retirement.fingerprints import IdentityKey
from retirement.intents import Intent
from retirement.interlock import RetirementUnavailable
from retirement.pages import INITIAL, encode, manifest, page_digest
from retirement.recovery import checked_event, checked_pages, event_digest


def record():
    now = datetime(2026, 11, 5, tzinfo=timezone.utc)
    value = Intent(
        *(str(uuid4()) for _ in range(4)),
        "chat_history_v1",
        now,
        2,
        2,
        0,
        False,
        1,
        ZERO,
        now + timedelta(microseconds=1),
    )
    return replace(value, event_digest=event_digest(value, ZERO))


def row(value):
    return (
        value.sequence,
        ZERO,
        value.event_digest,
        value.intent,
        value.owner,
        value.job,
        value.created_at,
        value.checkpointed_at,
        value.checkpointed_at,
        "sealed",
        value.scope,
        value.history_floor,
        value.privacy_floor,
        value.auth_floor,
        value.closed,
        value.fingerprint_count,
        value.fingerprint_root,
    )


def test_recovery_header_uses_the_exact_postgres_binary_event_chain():
    value = record()
    assert checked_event(value.installation, row(value), ZERO, 1) == (value, "sealed")
    assert event_digest(value, b"x" * 32) != value.event_digest


@pytest.mark.parametrize(
    "index,replacement",
    (
        (0, 2),
        (1, b"x" * 32),
        (2, b"x" * 32),
        (3, "33333333-3333-4333-8333-333333333333"),
        (4, "44444444-4444-4444-8444-444444444444"),
        (5, "55555555-5555-4555-8555-555555555555"),
        (6, datetime(2026, 11, 6, tzinfo=timezone.utc)),
        (8, None),
        (9, "unknown"),
        (10, "account_v1"),
        (11, 3),
        (12, 3),
        (13, 1),
        (14, True),
        (15, 1),
        (16, b"x" * 32),
    ),
)
def test_recovery_rejects_changed_original_metadata_before_floor_replay(
    index, replacement
):
    value = record()
    changed = list(row(value))
    changed[index] = replacement
    with pytest.raises(RetirementUnavailable):
        checked_event(value.installation, tuple(changed), ZERO, 1)


class Pages:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, values):
        assert "read_pages(%s,%s,4)" in sql and len(values) == 2
        return SimpleNamespace(
            fetchall=lambda: [r for r in self.rows if r[0] > values[1]][:4]
        )


def page_fixture():
    key = IdentityKey(str(uuid4()), b"fixture-recovery-key".ljust(32, b"0"))
    value = record()
    data = manifest(
        encode("0" * 64, key.mailbox("a@example.invalid")) for _ in range(1)
    )
    value = replace(
        value,
        scope="account_v1",
        closed=True,
        auth_floor=1,
        fingerprint_count=data.count,
        fingerprint_root=data.root,
    )
    pages = [(0, INITIAL, page_digest(INITIAL, 0, data.pages[0]), list(data.pages[0]))]
    return key, value, pages


def test_recovery_streams_only_the_complete_original_fingerprint_manifest():
    key, value, pages = page_fixture()
    checked_pages(Pages(pages), value, key.key_id)
    with pytest.raises(RetirementUnavailable):
        checked_pages(Pages([]), value, key.key_id)
    with pytest.raises(RetirementUnavailable):
        checked_pages(Pages(pages), value, str(uuid4()))


@pytest.mark.parametrize(
    "index,replacement", ((0, 1), (1, b"x" * 32), (2, b"x" * 32), (3, []))
)
def test_recovery_rejects_page_gaps_wrong_chain_and_shrunken_manifest(
    index, replacement
):
    key, value, pages = page_fixture()
    changed = list(pages[0])
    changed[index] = replacement
    with pytest.raises(RetirementUnavailable):
        checked_pages(Pages([tuple(changed)]), value, key.key_id)
