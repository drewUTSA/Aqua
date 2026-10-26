"""Reject owner claims, client results and unbounded workspace inputs."""

from typing import Literal
from uuid import UUID
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="after")
    def valid_text(self) -> Self:
        for name in self.__class__.model_fields:
            value = getattr(self, name)
            if isinstance(value, str):
                if "\x00" in value:
                    raise ValueError("workspace_text_invalid")
                try:
                    value.encode("utf-8")
                except UnicodeError:
                    raise ValueError("workspace_text_invalid") from None
        return self


class RequestKey(StrictBody):
    client_request_id: UUID


class Submission(RequestKey):
    question: str = Field(min_length=1, max_length=2000)
    model: Literal["gemini", "ollama"] | None = None


class FirstSubmission(Submission):
    project_id: UUID | None = None


class ChatSearch(StrictBody):
    search: str = Field(default="", max_length=80)
    archived: StrictBool = False
    project_id: UUID | None = None
    cursor: str | None = Field(default=None, max_length=1024)
    limit: int = Field(default=20, ge=1, le=100, strict=True)


class ChatPatch(StrictBody):
    revision: int = Field(ge=1, strict=True)
    title: str | None = Field(default=None, min_length=1, max_length=120)
    archived: StrictBool | None = None
    project_id: UUID | None = None

    @model_validator(mode="after")
    def changed(self) -> Self:
        if (
            not self.model_fields_set - {"revision"}
            or ("title" in self.model_fields_set and self.title is None)
            or ("archived" in self.model_fields_set and self.archived is None)
        ):
            raise ValueError("workspace_patch_invalid")
        return self


class ProjectCreate(RequestKey):
    name: str = Field(min_length=1, max_length=120)


class ProjectPatch(StrictBody):
    revision: int = Field(ge=1, strict=True)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    archived: StrictBool | None = None

    @model_validator(mode="after")
    def changed(self) -> Self:
        if not self.model_fields_set - {"revision"} or any(
            getattr(self, key) is None for key in self.model_fields_set - {"revision"}
        ):
            raise ValueError("workspace_patch_invalid")
        return self


class PromptCreate(RequestKey):
    label: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=2000)
    pinned: StrictBool = False


class PromptPatch(StrictBody):
    revision: int = Field(ge=1, strict=True)
    label: str | None = Field(default=None, min_length=1, max_length=120)
    prompt: str | None = Field(default=None, min_length=1, max_length=2000)
    pinned: StrictBool | None = None

    @model_validator(mode="after")
    def changed(self) -> Self:
        if not self.model_fields_set - {"revision"} or any(
            getattr(self, key) is None for key in self.model_fields_set - {"revision"}
        ):
            raise ValueError("workspace_patch_invalid")
        return self
