"""Closed P11a input/DTO; service authority checks precede every projection."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from privacy.policy import (
    CURSOR,
    FAILURE_CODES,
    MAX_EXPORT_BYTES,
    SCOPE,
    SHA256,
    STATES,
    identifier,
)

TOKEN = r"^v2\.[A-Za-z0-9_-]{43}$"


class ExportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    intent_id: str
    scope: Literal["personal_v1"]
    proof_token: str = Field(pattern=TOKEN, min_length=46, max_length=46, repr=False)

    @field_validator("intent_id")
    @classmethod
    def canonical_intent(cls, value):
        return identifier(value)


class ExportProofIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation: Literal["data_export"]
    target_intent_id: str

    @field_validator("target_intent_id")
    @classmethod
    def canonical_intent(cls, value):
        return identifier(value)


class ExportReviewQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    cursor: str | None = None

    @field_validator("cursor")
    @classmethod
    def closed_cursor(cls, value):
        if value is not None and not CURSOR.fullmatch(value):
            raise ValueError("export_cursor_invalid")
        return value


def timestamp(value: object) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("export_timestamp_invalid")
    return value.isoformat()


def public_job(row: dict) -> dict:
    """Call only after current owner/session/epoch/expiry/grant projection.

    Invalidation is projected to expired before this function. Database output
    fields never bleed into queued/working/expired replies through **row copies.
    """
    state = row.get("state")
    if type(state) is not str or state not in STATES or row.get("scope") != SCOPE:
        raise ValueError("export_job_state_invalid")
    result = {
        "id": identifier(str(row["id"])),
        "intent_id": identifier(str(row["intent_id"])),
        "scope": SCOPE,
        "state": state,
        "created_at": timestamp(row["created_at"]),
        "expires_at": timestamp(row["expires_at"]),
    }
    if state == "ready":
        size, digest = row.get("byte_count"), row.get("sha256")
        if (
            type(size) is not int
            or not 1 <= size <= MAX_EXPORT_BYTES
            or type(digest) is not str
            or not SHA256.fullmatch(digest)
        ):
            raise ValueError("export_ready_metadata_invalid")
        result.update(byte_count=size, sha256=digest)
    elif state == "failed":
        code = row.get("error_code")
        if type(code) is not str or code not in FAILURE_CODES:
            raise ValueError("export_failure_code_invalid")
        result["error_code"] = code
    return result
