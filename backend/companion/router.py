"""Private help routes accept data only and cannot submit analytical work."""

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, field_validator

from companion.data_contract import CompanionDenied, _text
from companion.policy import CompanionPolicy
from companion.service import Help
from workspace.dependencies import Service, Session, perform
from workspace.errors import WorkspaceError

router = APIRouter(prefix="/api/v1/companion", tags=["private Aqua help"])


class HelpQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schemaVersion: StrictInt
    question: StrictStr

    @field_validator("schemaVersion")
    @classmethod
    def version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("help_version_invalid")
        return value

    @field_validator("question")
    @classmethod
    def bounded(cls, value: str) -> str:
        if not _text(value, 8000) or len(value) > 2000:
            raise ValueError("help_question_invalid")
        return value


def read(
    request: Request, session: Any, workspace: Any, question: str | None = None
) -> dict:
    """The feature flag is typed app policy, never a new analytical authority."""
    policy = getattr(request.app.state, "companion_policy", CompanionPolicy())
    if type(policy) is not CompanionPolicy or not policy.enabled:
        raise WorkspaceError("not_found", 404)
    if request.query_params:
        raise WorkspaceError("invalid_request", 422)
    try:
        return Help(workspace).read(session, question=question)
    except CompanionDenied:
        raise WorkspaceError("service_unavailable", 503) from None


@router.get("/capabilities")
def capabilities(request: Request, session: Session, workspace: Service) -> Any:
    return perform(lambda: read(request, session, workspace))


@router.post("/help")
def help_answer(
    body: HelpQuestion, request: Request, session: Session, workspace: Service
) -> Any:
    return perform(lambda: read(request, session, workspace, body.question))
