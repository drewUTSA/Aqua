"""Closed settings records reject all-or-nothing, including JSON type confusion."""

from copy import deepcopy
import pytest
from pydantic import ValidationError
from preferences.contracts import PreferenceUpdate
from preferences.schema import DEFAULTS, OPTIONS, validate_values


def update(**changes):
    return {
        "schemaVersion": 1,
        "expectedRevision": 1,
        "values": deepcopy(DEFAULTS),
        **changes,
    }


@pytest.mark.parametrize("key", OPTIONS)
def test_every_enum_accepts_only_its_bounded_values(key):
    for value in OPTIONS[key]:
        body = update(values={**deepcopy(DEFAULTS), key: value})
        assert PreferenceUpdate.model_validate(body).values[key] == value
    with pytest.raises(ValidationError):
        PreferenceUpdate.model_validate(
            update(values={**deepcopy(DEFAULTS), key: "<script>"})
        )


@pytest.mark.parametrize("value", [True, 1.0, "1", None, 0, 2, -1])
def test_schema_version_has_exact_json_integer_type(value):
    with pytest.raises(ValidationError):
        PreferenceUpdate.model_validate(update(schemaVersion=value))


@pytest.mark.parametrize("value", [True, 1.0, "1", None, 0, -1, 9007199254740992])
def test_revision_rejects_coercion_and_unsafe_browser_integers(value):
    with pytest.raises(ValidationError):
        PreferenceUpdate.model_validate(update(expectedRevision=value))


@pytest.mark.parametrize(
    "key,value",
    [
        ("recents_count", True),
        ("recents_count", 10.0),
        ("suggestions", 1),
        ("wrap_code", "false"),
        ("sidebar_sections", ["recents", "recents"]),
        ("sidebar_sections", ["__proto__"]),
        ("sidebar_sections", "projects"),
        ("sidebar_sections", [None]),
        ("sidebar_sections", {"projects": True}),
        ("precision", 2),
        ("timezone", "javascript:alert(1)"),
    ],
)
def test_nested_and_type_confusion_never_changes_input(key, value):
    body = update(values={**deepcopy(DEFAULTS), key: value})
    before = deepcopy(body)
    with pytest.raises(ValidationError):
        PreferenceUpdate.model_validate(body)
    assert body == before


@pytest.mark.parametrize(
    "field",
    [
        "owner_id",
        "roles",
        "__proto__",
        "constructor",
        "consent",
        "text_size",
        "personal_instructions",
    ],
)
def test_snapshot_forbids_unknown_security_and_device_fields(field):
    with pytest.raises(ValidationError):
        PreferenceUpdate.model_validate(
            update(values={**deepcopy(DEFAULTS), field: "forged"})
        )
    with pytest.raises(ValidationError):
        PreferenceUpdate.model_validate({**update(), field: "forged"})


def test_missing_read_keys_use_defaults_but_writes_require_complete_snapshot():
    loaded = validate_values({"accent": "sage"}, complete=False)
    assert loaded == {**DEFAULTS, "accent": "sage"}
    loaded["sidebar_sections"].clear()
    assert DEFAULTS["sidebar_sections"] == ["projects", "recents", "prompts"]
    with pytest.raises(ValidationError):
        PreferenceUpdate.model_validate(update(values={"accent": "sage"}))


def test_empty_or_reordered_sidebar_is_valid_without_removing_primary_controls():
    for sections in [[], ["prompts", "projects"]]:
        body = PreferenceUpdate.model_validate(
            update(values={**DEFAULTS, "sidebar_sections": sections})
        )
        assert body.values["sidebar_sections"] == sections
