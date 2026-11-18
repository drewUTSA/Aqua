"""A result identifier/column selection is input, never result data or authority."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

from companion.policy import CompanionPolicy
from result_companion.service import ResultCompanion
from workspace.dependencies import Service, Session, perform
from workspace.errors import WorkspaceError

router = APIRouter(prefix="/api/v1/companion", tags=["private saved result assistance"])


class BriefRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    schemaVersion: StrictInt
    request_id: StrictStr = Field(
        pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"
    )
    column_index: StrictInt = Field(ge=0, le=63)

    @field_validator("schemaVersion")
    @classmethod
    def version(cls, value):
        if value != 1:
            raise ValueError("result_companion_version_invalid")
        return value


def read(request, body, session, workspace):
    if request.query_params:
        raise WorkspaceError("invalid_request", 422)
    policy = getattr(request.app.state, "companion_policy", CompanionPolicy())
    try:
        return ResultCompanion(workspace, policy).read(
            session, request_id=body.request_id, column_index=body.column_index
        )
    except (ValueError, KeyError, TypeError, IndexError, OverflowError, RecursionError):
        raise WorkspaceError("service_unavailable", 503) from None


@router.post("/result-brief")
def result_brief(
    body: BriefRequest, request: Request, session: Session, workspace: Service
):
    return perform(lambda: read(request, body, session, workspace))
