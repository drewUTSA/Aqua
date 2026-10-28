"""Only the supported profile field can enter the account update boundary."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from account.policy import MAX_REVISION, display_name


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expectedRevision: int = Field(ge=1, le=MAX_REVISION, strict=True)
    display_name: str = Field(min_length=1, max_length=120, strict=True)

    @field_validator("display_name", mode="before")
    @classmethod
    def plain_name(cls, value: object) -> str:
        return display_name(value)
