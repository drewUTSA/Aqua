"""New deletion intent boundaries stay v4 without rewriting retained records."""

from datetime import datetime, timedelta, timezone
import hashlib
import json

from pydantic import ValidationError
import pytest

from account.action_contracts import ActionTarget
from account.identity_contracts import IdentityTarget
from account.policy import target_digest
from privacy.deletion_contracts import DeletionCreate, public_job
from retirement import deletion_policy as policy
from retirement.fingerprints import canonical_uuid
from retirement.intents import Intent, replay

OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
INTENT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
OLD = "bbbbbbbb-bbbb-1bbb-8bbb-bbbbbbbbbbbb"
NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)
OPERATIONS = ("history_delete", "account_delete")
BAD = (
    "00000000-0000-0000-0000-000000000000",
    OLD,
    "bbbbbbbb-bbbb-3bbb-8bbb-bbbbbbbbbbbb",
    "bbbbbbbb-bbbb-5bbb-8bbb-bbbbbbbbbbbb",
    INTENT.upper(),
    True,
    "bbbbbbbb-bbbb-4bbb-0bbb-bbbbbbbbbbbb",
)


def body(operation, intent):
    scope = policy.SCOPES[operation]
    return {
        "intent_id": intent,
        "scope": scope,
        "confirmation": policy.CONFIRMATIONS[scope],
        "proof_token": "v2." + "p" * 43,
        "receipt_token": "v2." + "r" * 43,
    }


def job(scope, state, intent=INTENT):
    return {
        "id": OWNER,
        "intent_id": intent,
        "scope": scope,
        "state": state,
        "created_at": NOW,
        "receipt_expires_at": NOW + timedelta(seconds=600),
    }


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("intent", BAD)
def test_new_destructive_intents_and_both_proof_dtos_reject_non_v4(operation, intent):
    with pytest.raises(ValidationError):
        DeletionCreate.model_validate(body(operation, intent))
    for model in (ActionTarget, IdentityTarget):
        with pytest.raises(ValidationError):
            model.model_validate({"operation": operation, "target_intent_id": intent})
    with pytest.raises(ValueError):
        target_digest(operation, intent)


@pytest.mark.parametrize("operation", OPERATIONS)
def test_valid_v4_targets_keep_existing_exact_digest_bytes(operation):
    assert DeletionCreate.model_validate(body(operation, INTENT)).intent_id == INTENT
    for model in (ActionTarget, IdentityTarget):
        assert (
            model.model_validate(
                {"operation": operation, "target_intent_id": INTENT}
            ).target_intent_id
            == INTENT
        )
    expected = hashlib.sha256(
        json.dumps(
            ["aqua-account-action-v1", operation, [policy.SCOPES[operation], INTENT]],
            separators=(",", ":"),
        ).encode()
    ).digest()
    assert (
        target_digest(operation, INTENT)
        == policy.target_digest(operation, INTENT)
        == expected
    )


@pytest.mark.parametrize("scope", tuple(policy.CONFIRMATIONS))
@pytest.mark.parametrize(
    "state", ("awaiting_authority", "accepted", "purging", "complete")
)
def test_public_metadata_accepts_only_its_literal_bool_and_state_pair(scope, state):
    accepted = state != "awaiting_authority"
    reply = public_job(job(scope, state), acceptance_confirmed=accepted)
    assert reply["accepted"] is accepted
    assert reply["cleanup_complete"] is (state == "complete")
    for flag in (not accepted, 0, 1, None, "true", "false"):
        with pytest.raises(ValueError):
            public_job(job(scope, state), acceptance_confirmed=flag)


@pytest.mark.parametrize("scope", tuple(policy.CONFIRMATIONS))
def test_retained_legacy_intents_still_reconcile_at_the_original_floor(scope):
    closed = scope == "account_v1"
    known = Intent(
        OWNER,
        OWNER,
        OLD,
        OWNER,
        scope,
        NOW,
        2,
        2,
        int(closed),
        closed,
        sequence=1,
        event_digest=b"e" * 32,
        checkpointed_at=NOW + timedelta(seconds=1),
        fingerprint_count=int(closed),
        **({"fingerprint_root": b"r" * 32} if closed else {}),
    )
    result = replay(known, installation=OWNER, owner=OWNER, intent=OLD, scope=scope)
    assert result.action == "replay_pending" and result.history_floor == 2
    assert (
        result.job == OWNER
        and result.acceptance_confirmed is True
        and result.cleanup_complete is False
    )
    assert (
        public_job(job(scope, "accepted", OLD), acceptance_confirmed=True)["intent_id"]
        == OLD
    )
    for value in BAD[:4]:
        assert canonical_uuid(value) == value
    # Legacy export and non-deletion targets retain their previous UUID policy.
    for model in (ActionTarget, IdentityTarget):
        assert (
            model.model_validate(
                {"operation": "data_export", "target_intent_id": OLD}
            ).target_intent_id
            == OLD
        )
