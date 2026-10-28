"""Profile mass assignment and lossy JSON numeric coercions are rejected."""

import pytest
from pydantic import ValidationError

from account.contracts import ProfileUpdate


@pytest.mark.parametrize(
    "revision", [True, False, 1.0, "1", None, 0, -1, 9007199254740992]
)
def test_profile_revision_has_exact_bounded_integer_type(revision):
    with pytest.raises(ValidationError):
        ProfileUpdate.model_validate(
            {"expectedRevision": revision, "display_name": "New name"}
        )


@pytest.mark.parametrize(
    "key",
    [
        "owner_id",
        "user_id",
        "email",
        "verified",
        "picture",
        "method",
        "role",
        "grant",
        "proof",
        "__proto__",
    ],
)
def test_profile_contract_excludes_security_and_owner_fields(key):
    with pytest.raises(ValidationError):
        ProfileUpdate.model_validate(
            {"expectedRevision": 1, "display_name": "New name", key: "forged"}
        )


def test_profile_contract_normalizes_supported_name_without_coercion():
    body = ProfileUpdate.model_validate(
        {"expectedRevision": 1, "display_name": "  Ame\u0301lie  "}
    )
    assert body.model_dump() == {"expectedRevision": 1, "display_name": "Amélie"}
    with pytest.raises(ValidationError):
        ProfileUpdate.model_validate({"expectedRevision": 1, "display_name": 123})
