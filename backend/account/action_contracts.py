"""Only implemented actions and bounded opaque tokens cross this boundary."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from account.policy import identifier
from auth.password_policy import normalize_email

TOKEN = r"^v2\.[A-Za-z0-9_-]{43}$"


class ActionTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    operation: Literal[
        "password_change",
        "email_change",
        "google_link",
        "google_unlink",
        "session_revoke",
        "sessions_revoke_all",
    ]
    target_session_id: str | None = None
    target_identity_id: str | None = None
    new_email: str | None = Field(default=None, max_length=254)

    @model_validator(mode="after")
    def exact_target(self) -> "ActionTarget":
        if self.operation == "session_revoke":
            identifier(self.target_session_id)
        elif self.target_session_id is not None:
            raise ValueError("account_target_invalid")
        if self.operation == "google_unlink":
            identifier(self.target_identity_id)
        elif self.target_identity_id is not None:
            raise ValueError("account_target_invalid")
        if self.operation == "email_change":
            try:
                self.new_email = normalize_email(self.new_email)
            except (TypeError, ValueError, RuntimeError):
                raise ValueError("account_target_invalid") from None
        elif self.new_email is not None:
            raise ValueError("account_target_invalid")
        return self


class PasswordReauth(ActionTarget):
    challenge_id: str
    challenge_token: str = Field(
        pattern=TOKEN, min_length=46, max_length=46, repr=False
    )
    password: str = Field(min_length=1, max_length=512, repr=False)

    @field_validator("challenge_id")
    @classmethod
    def canonical_id(cls, value: str) -> str:
        return identifier(value)


class ActionProof(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    proof_token: str = Field(pattern=TOKEN, min_length=46, max_length=46, repr=False)


class PasswordChange(ActionProof):
    new_password: str = Field(min_length=1, max_length=512, repr=False)
