"""No owner, generation, expiry or permission can enter a deletion request."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from retirement.deletion_policy import CONFIRMATIONS, STATES, intent_identifier
from retirement.fingerprints import canonical_uuid

TOKEN = r"^v2\.[A-Za-z0-9_-]{43}$"


class DeletionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    intent_id: str
    scope: Literal["chat_history_v1", "account_v1"]
    proof_token: str = Field(pattern=TOKEN, min_length=46, max_length=46, repr=False)
    receipt_token: str = Field(pattern=TOKEN, min_length=46, max_length=46, repr=False)
    confirmation: Literal["DELETE HISTORY", "DELETE ACCOUNT"]

    @field_validator("intent_id")
    @classmethod
    def canonical_intent(cls, value):
        return intent_identifier(value)

    @model_validator(mode="after")
    def exact_confirmation(self):
        if self.confirmation != CONFIRMATIONS[self.scope]:
            raise ValueError("deletion_confirmation_invalid")
        if self.receipt_token == self.proof_token:
            raise ValueError("deletion_receipt_invalid")
        return self


def public_job(row, *, acceptance_confirmed):
    """A missing row or unconfirmed checkpoint is never physical completion."""
    if row["state"] not in STATES:
        raise ValueError("deletion_state_invalid")
    if type(acceptance_confirmed) is not bool or acceptance_confirmed != (
        row["state"] != "awaiting_authority"
    ):
        raise ValueError("deletion_acceptance_unconfirmed")
    return {
        "id": canonical_uuid(str(row["id"])),
        "intent_id": canonical_uuid(str(row["intent_id"])),
        "scope": row["scope"],
        "state": row["state"],
        "accepted": acceptance_confirmed,
        "cleanup_complete": row["state"] == "complete" and acceptance_confirmed,
        "created_at": row["created_at"].isoformat(),
        "receipt_expires_at": row["receipt_expires_at"].isoformat(),
    }
