"""Closed identity-action DTOs; ownership and verification are never submitted."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from account.action_contracts import TOKEN, ActionProof
from account.policy import identifier
from auth.password_policy import normalize_email


class IdentityTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation: Literal[
        "password_change",
        "password_add",
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
    def exact_target(self):
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


class GoogleChallenge(IdentityTarget):
    identity_id: str

    @field_validator("identity_id")
    @classmethod
    def canonical_id(cls, value):
        return identifier(value)


class GoogleVerification(IdentityTarget):
    challenge_id: str
    challenge_token: str = Field(
        pattern=TOKEN, min_length=46, max_length=46, repr=False
    )
    credential: str = Field(min_length=1, max_length=8192, repr=False)

    @field_validator("challenge_id")
    @classmethod
    def canonical_id(cls, value):
        return identifier(value)


class GoogleCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    challenge_id: str
    challenge_token: str = Field(
        pattern=TOKEN, min_length=46, max_length=46, repr=False
    )
    credential: str = Field(min_length=1, max_length=8192, repr=False)

    @field_validator("challenge_id")
    @classmethod
    def canonical_id(cls, value):
        return identifier(value)


class GoogleLink(ActionProof):
    candidate_token: str = Field(
        pattern=TOKEN, min_length=46, max_length=46, repr=False
    )


class EmailRequest(ActionProof):
    new_email: str = Field(min_length=3, max_length=254)

    @field_validator("new_email")
    @classmethod
    def mailbox(cls, value):
        try:
            return normalize_email(value)
        except RuntimeError:
            raise ValueError("account_target_invalid") from None


class MailCompletion(ActionProof):
    request_id: str
    request_token: str = Field(pattern=TOKEN, min_length=46, max_length=46, repr=False)
    email_token: str = Field(
        pattern=r"^[A-Za-z0-9_-]{43}$", min_length=43, max_length=43, repr=False
    )

    @field_validator("request_id")
    @classmethod
    def canonical_id(cls, value):
        return identifier(value)


class PasswordEnrollment(MailCompletion):
    new_password: str = Field(min_length=1, max_length=512, repr=False)


class EmailCompletion(MailCompletion):
    old_email_token: str = Field(
        pattern=r"^[A-Za-z0-9_-]{43}$", min_length=43, max_length=43, repr=False
    )


class NotificationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expectedRevision: int = Field(ge=1, le=9007199254740991)
    in_app_success: bool
    preview: Literal["generic", "hidden"]
