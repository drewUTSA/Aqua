"""Destructive proof targets are fixed scopes and intents, never client floors."""

import hashlib
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from account.action_contracts import ActionTarget, PasswordReauth
from account.identity_contracts import (
    GoogleChallenge,
    GoogleVerification,
    IdentityTarget,
)
from account.identity_runtime import action_target
from account.policy import target_digest
from retirement.deletion_policy import target_digest as deletion_target

INTENT = "00000000-0000-4000-8000-000000000901"
TOKEN = "v2." + "x" * 43
METHOD = "00000000-0000-4000-8000-000000000902"


@pytest.mark.parametrize("operation", ["history_delete", "account_delete"])
def test_destructive_targets_use_only_exact_canonical_intents(operation):
    for model in (ActionTarget, IdentityTarget):
        body = model.model_validate(
            {"operation": operation, "target_intent_id": INTENT}
        )
        assert action_target(None, body) == INTENT
    assert target_digest(operation, INTENT) == deletion_target(operation, INTENT)
    assert target_digest(operation, INTENT) != deletion_target(operation, str(uuid4()))
    other = "account_delete" if operation == "history_delete" else "history_delete"
    assert target_digest(operation, INTENT) != target_digest(other, INTENT)


@pytest.mark.parametrize("operation", ["history_delete", "account_delete"])
def test_destructive_target_contracts_reject_other_resources_and_server_floors(
    operation,
):
    valid = {"operation": operation, "target_intent_id": INTENT}
    for model in (ActionTarget, IdentityTarget):
        for key, value in {
            "target_session_id": METHOD,
            "target_identity_id": METHOD,
            "new_email": "forged@example.invalid",
            "owner_id": METHOD,
            "privacy_epoch": 4,
            "history_generation": 4,
            "auth_epoch": 4,
            "verified": True,
            "scope": "arbitrary_v1",
        }.items():
            with pytest.raises(ValidationError):
                model.model_validate({**valid, key: value})
        for value in (None, "", INTENT.upper().replace("901", "ABC"), "bad", 2, True):
            with pytest.raises(ValidationError):
                model.model_validate({**valid, "target_intent_id": value})


def test_password_google_dtos_keep_opaque_credentials_and_target_separation():
    target = {"operation": "history_delete", "target_intent_id": INTENT}
    password = PasswordReauth.model_validate(
        {
            **target,
            "challenge_id": METHOD,
            "challenge_token": TOKEN,
            "password": "private-fixture",
        }
    )
    google = GoogleVerification.model_validate(
        {
            **target,
            "challenge_id": METHOD,
            "challenge_token": TOKEN,
            "credential": "private-provider-fixture",
        }
    )
    start = GoogleChallenge.model_validate({**target, "identity_id": METHOD})
    assert start.target_intent_id == INTENT
    assert TOKEN not in repr(password) and "private-fixture" not in repr(password)
    assert TOKEN not in repr(google) and "private-provider-fixture" not in repr(google)
    with pytest.raises(ValidationError):
        PasswordReauth.model_validate({**password.model_dump(), "privacy_epoch": 1})


@pytest.mark.parametrize(
    "operation", ["sessions_revoke_all", "password_change", "google_link"]
)
def test_prior_action_digest_bytes_and_target_rejections_remain_unchanged(operation):
    expected = hashlib.sha256(
        json.dumps(
            ["aqua-account-action-v1", operation, None], separators=(",", ":")
        ).encode()
    ).digest()
    assert target_digest(operation) == expected
    for model in (ActionTarget, IdentityTarget):
        with pytest.raises(ValidationError):
            model.model_validate({"operation": operation, "target_intent_id": INTENT})


def test_account_capability_schema_does_not_gain_destructive_proof_flags():
    from account.policy import CAPABILITIES

    assert len(CAPABILITIES) == 13
    assert "history_delete" not in CAPABILITIES and "account_delete" not in CAPABILITIES
