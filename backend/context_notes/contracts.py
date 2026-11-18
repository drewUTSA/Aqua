"""Closed input DTOs contain content and expected versions, never ownership."""

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from context_notes import rules
from context_notes.policy import MAX_REVISION


class ExpectedScope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    schemaVersion: StrictInt
    expected_scope_id: str = Field(pattern=r"^[a-f0-9]{64}$", strict=True)

    @field_validator("schemaVersion")
    @classmethod
    def version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("note_version_invalid")
        return value


class NoteContent(ExpectedScope):
    kind: str = Field(strict=True)
    label: str = Field(strict=True)
    body: str = Field(strict=True)

    @field_validator("kind")
    @classmethod
    def kind_value(cls, value: str) -> str:
        if value not in {"note", "metric_definition"}:
            raise ValueError("note_kind_invalid")
        return value

    @field_validator("label")
    @classmethod
    def label_value(cls, value: str) -> str:
        return rules.text(value, label=True)

    @field_validator("body")
    @classmethod
    def body_value(cls, value: str) -> str:
        return rules.text(value)


class NoteCreate(NoteContent):
    client_request_id: str = Field(strict=True)

    @field_validator("client_request_id")
    @classmethod
    def request_identifier(cls, value: str) -> str:
        return rules.identifier(value)


class NotePatch(NoteContent):
    revision: StrictInt = Field(ge=1, le=MAX_REVISION)


class NoteSelection(ExpectedScope):
    revision: StrictInt = Field(ge=1, le=MAX_REVISION)
