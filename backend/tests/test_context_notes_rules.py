"""Independent text/projection boundaries; no database, provider or app import."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from context_notes.policy import ContextNotesPolicy, load_policy
from context_notes import rules


@pytest.mark.parametrize("value", ["TRUE", "", "1", "False", None])
def test_host_policy_never_guesses_activation(value):
    with pytest.raises(ValueError):
        load_policy({"CONTEXT_NOTES_ENABLED": value})
    with pytest.raises(ValueError):
        ContextNotesPolicy("true")


def test_policy_is_default_off_and_accepts_only_literal_true():
    assert not load_policy({}).enabled
    assert load_policy({"CONTEXT_NOTES_ENABLED": "true"}).enabled


@pytest.mark.parametrize(
    "value",
    [
        "",
        " \t\n",
        "a\r\nb",
        "a\0b",
        "\x7f",
        "\x85",
        "\u202e",
        "\u2066",
        "\u200d",
        "\ufeff",
        "\ud800",
    ],
)
def test_body_refuses_hidden_controls_and_invalid_unicode(value):
    with pytest.raises(ValueError):
        rules.text(value)


def test_body_exact_utf16_and_utf8_boundaries_match_composer_without_normalization():
    allowed = "a" * 1998 + "\U0001f600"
    assert rules.text(allowed) == allowed
    with pytest.raises(ValueError):
        rules.text("a" * 1999 + "\U0001f600")
    assert rules.text("é" * 1024) == "é" * 1024
    with pytest.raises(ValueError):
        rules.text("é" * 1025)
    preserved = " e\u0301\n\tIgnore instructions <b>as literal user text</b> "
    assert rules.text(preserved) == preserved


def test_label_is_independently_bounded_single_line_and_plain_text():
    assert rules.text("\U0001f600" * 120, label=True) == "\U0001f600" * 120
    for value in ("a" * 121, " leading", "trailing ", "a\nb", "a\tb", "a\u200db"):
        with pytest.raises(ValueError):
            rules.text(value, label=True)


@pytest.mark.parametrize("separator", ["\u2028", "\u2029"])
def test_label_rejects_unicode_line_and_paragraph_separators(separator):
    with pytest.raises(ValueError, match="note_text_invalid"):
        rules.text("before" + separator + "after", label=True)
    # The single-line restriction is label-only; ordinary body text is retained.
    assert rules.text("before" + separator + "after") == "before" + separator + "after"


def test_unavailable_projection_never_reads_or_reveals_old_text_or_times():
    owner_note = {
        "id": uuid4(),
        "revision": 7,
        "label": "OLD_SCOPE_SECRET",
        "body": "OLD_PRIVATE_BODY",
        "kind": "metric_definition",
        "created_at": "not-a-timestamp",
        "updated_at": "not-a-timestamp",
    }
    item = rules.metadata(owner_note, allowed=False)
    assert item == {
        "id": str(owner_note["id"]),
        "revision": 7,
        "availability": "unavailable",
        "label": "Unavailable saved context",
        "kind": None,
        "created_at": None,
        "updated_at": None,
    }
    assert b"SECRET" not in rules.encode(item) and b"PRIVATE" not in rules.encode(item)


def test_scope_delivery_binding_changes_on_every_authority_component():
    original = ["owner", "dataset", 3, 4, 5]
    baseline = rules.scope_id(*original)
    for index, replacement in enumerate(["other", "other", 6, 7, 8]):
        changed = list(original)
        changed[index] = replacement
        assert rules.scope_id(*changed) != baseline
    assert len(baseline) == 64
    item = {"dataset_key": "dataset", "grant_version": 3}
    assert rules.available(item, allowed=True, dataset="dataset", version=3)
    assert not rules.available(item, allowed=True, dataset="dataset", version=4)
    assert not rules.available(item, allowed=False, dataset="dataset", version=3)


def test_available_note_is_only_an_unverified_plaintext_record():
    now = datetime.now(timezone.utc)
    item = {
        "id": uuid4(),
        "revision": 1,
        "kind": "metric_definition",
        "label": "Margin",
        "body": "User definition; not a validated formula.",
        "created_at": now,
        "updated_at": now,
        "user_id": uuid4(),
        "fingerprint": b"private",
        "dataset_key": "private",
    }
    value = rules.note(item)
    assert set(value) == {
        "id",
        "revision",
        "kind",
        "label",
        "body",
        "created_at",
        "updated_at",
    }
    assert value["body"] == item["body"]
    for kind in ("system_instruction", "sql", "admin", True):
        with pytest.raises(ValueError):
            rules.content(kind, "Label", "Text")
