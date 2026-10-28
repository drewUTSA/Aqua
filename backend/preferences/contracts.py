"""Closed full-snapshot update contract, with no caller-controlled owner."""

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from preferences.schema import MAX_REVISION, validate_values


class PreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schemaVersion: Literal[1]
    expectedRevision: int = Field(ge=1, le=MAX_REVISION, strict=True)
    values: dict[str, Any]

    @field_validator("schemaVersion", mode="before")
    @classmethod
    def exact_version(cls, value: Any) -> int:
        if type(value) is not int or value != 1:
            raise ValueError("preferences_schema_invalid")
        return value

    @field_validator("values", mode="before")
    @classmethod
    def closed_values(cls, value: Any) -> dict:
        return validate_values(value, complete=True)
