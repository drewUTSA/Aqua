"""Destructive inputs and metadata receipts never authorize ordinary content."""

from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest
from pydantic import ValidationError

from privacy.deletion_contracts import DeletionCreate, public_job
from retirement import deletion_policy as policy
from retirement.fingerprints import IdentityKey
from retirement.interlock import RetirementUnavailable
from retirement.settings import parse

OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
INTENT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
OTHER = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
TOKEN = "v2." + "a" * 43


def body(**changes):
    return {
        "intent_id": INTENT,
        "scope": "chat_history_v1",
        "proof_token": TOKEN,
        "receipt_token": "v2." + "b" * 43,
        "confirmation": "DELETE HISTORY",
        **changes,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"user_id": OWNER},
        {"history_floor": 2},
        {"expires_at": "tomorrow"},
        {"scope": "account_v1"},
        {"confirmation": "delete history"},
        {"receipt_token": "public-job-id"},
        {"intent_id": INTENT.upper()},
    ],
)
def test_destructive_body_rejects_owner_floors_wrong_confirmation_and_receipt(changes):
    with pytest.raises(ValidationError):
        DeletionCreate.model_validate(body(**changes))


def test_receipt_and_fresh_proof_are_separate_redacted_inputs():
    value = DeletionCreate.model_validate(body())
    assert value.scope == "chat_history_v1"
    assert value.receipt_token not in repr(value)
    assert value.proof_token not in repr(value)
    assert policy.receipt_digest(value.receipt_token) != policy.receipt_digest(
        value.proof_token
    )


def test_action_target_commits_both_exact_scope_and_intent():
    original = policy.target_digest("history_delete", INTENT)
    assert original != policy.target_digest("account_delete", INTENT)
    assert original != policy.target_digest("history_delete", OTHER)
    with pytest.raises(ValueError):
        policy.target_digest("data_export", INTENT)


def test_independent_signed_job_binding_changes_for_every_receipt_context():
    values = (
        "synthetic-session-secret-" * 3,
        OWNER,
        OWNER,
        INTENT,
        "account_v1",
        b"s" * 32,
        b"t" * 32,
    )
    expected = policy.job_identifier(*values)
    assert expected == policy.job_identifier(*values)
    for index, replacement in (
        (1, OTHER),
        (2, OTHER),
        (3, OTHER),
        (4, "chat_history_v1"),
        (5, b"x" * 32),
        (6, b"y" * 32),
    ):
        changed = list(values)
        changed[index] = replacement
        assert expected != policy.job_identifier(*changed)


def job(state="awaiting_authority"):
    now = datetime(2026, 11, 5, tzinfo=timezone.utc)
    return {
        "id": OWNER,
        "intent_id": INTENT,
        "scope": "account_v1",
        "state": state,
        "created_at": now,
        "receipt_expires_at": now + timedelta(seconds=600),
        "receipt_digest": b"hidden",
        "origin_session_digest": b"hidden",
        "manifest": b"private",
        "history_floor": 2,
    }


@pytest.mark.parametrize("state", ["accepted", "purging", "complete"])
def test_public_metadata_never_claims_acceptance_without_protected_confirmation(state):
    with pytest.raises(ValueError):
        public_job(job(state), acceptance_confirmed=False)
    result = public_job(job(state), acceptance_confirmed=True)
    assert result["accepted"] is True
    assert result["cleanup_complete"] is (state == "complete")
    assert (
        not {"manifest", "receipt_digest", "origin_session_digest", "history_floor"}
        & result.keys()
    )


def test_unconfirmed_metadata_is_not_instant_deletion():
    result = public_job(job(), acceptance_confirmed=False)
    assert result["accepted"] is False
    assert result["cleanup_complete"] is False


def config():
    material = b"synthetic-retirement-key".ljust(32, b"0")
    key = IdentityKey(OWNER, material)
    return material, {
        "installation_id": OWNER,
        "identity_key_id": OWNER,
        "key_commitment": key.commitment.hex(),
        "public_key": hashlib.sha256(b"synthetic-public-key").hexdigest(),
        "writer_dsn": "postgresql://aqua_retirement_writer:"
        + "a" * 43
        + "@/aqua_retirement?host=/run/aqua-app-db&port=5432&sslmode=disable",
    }


def test_independent_config_accepts_only_fixed_role_socket_and_key_commitment():
    material, value = config()
    assert parse(json.dumps(value).encode(), material).installation == OWNER
    for name, replacement in (
        (
            "writer_dsn",
            value["writer_dsn"].replace("aqua_retirement_writer", "aqua_app_runtime"),
        ),
        ("writer_dsn", value["writer_dsn"].replace("/run/aqua-app-db", "127.0.0.1")),
        ("key_commitment", "0" * 64),
        ("public_key", "bad"),
        ("installation_id", OWNER.upper()),
    ):
        changed = {**value, name: replacement}
        with pytest.raises(RetirementUnavailable):
            parse(json.dumps(changed).encode(), material)
    with pytest.raises(RetirementUnavailable):
        parse(
            json.dumps({**value, "private_signing_key": "not permitted"}).encode(),
            material,
        )
    duplicate = json.dumps(value)[:-1] + ',"public_key":"' + "0" * 64 + '"}'
    with pytest.raises(RetirementUnavailable):
        parse(duplicate.encode(), material)
