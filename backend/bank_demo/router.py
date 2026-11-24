"""Private, typed reports doorway; client values never select demo authority."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

from bank_demo.policy import BankDemoPolicy
from bank_demo.requirements import ReportRequirements
from bank_demo.service import BankDemo
from workspace.dependencies import Service, Session, perform
from workspace.errors import WorkspaceError

router = APIRouter(prefix="/api/v1/bank-demo", tags=["private fictional bank demo"])


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    schemaVersion: StrictInt
    report_id: StrictStr = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    expected_source_revision: StrictStr = Field(pattern=r"^[a-f0-9]{64}$")
    requirements: ReportRequirements | None = None

    @field_validator("requirements", mode="before")
    @classmethod
    def supplied_requirements(cls, value):
        if value is None:
            raise ValueError("bank_demo_requirements_invalid")
        return value

    @field_validator("schemaVersion")
    @classmethod
    def version(cls, value):
        if value != 1:
            raise ValueError("bank_demo_version_invalid")
        return value


def read(request, session, workspace, body=None):
    if request.query_params:
        raise WorkspaceError("invalid_request", 422)
    policy = getattr(request.app.state, "bank_demo_policy", BankDemoPolicy())
    try:
        demo = BankDemo(workspace, policy)
        if body is None:
            return demo.read(session)
        return demo.read(
            session,
            report_id=body.report_id,
            expected_source_revision=body.expected_source_revision,
            requirements=body.requirements,
        )
    except (ValueError, KeyError, TypeError, ImportError, UnicodeError):
        # Only fixed safe metadata leaves the adapter, never core/input diagnostics.
        raise WorkspaceError("service_unavailable", 503) from None


@router.get("/context")
def context(request: Request, session: Session, workspace: Service):
    return perform(lambda: read(request, session, workspace))


@router.post("/reports")
def report(body: ReportRequest, request: Request, session: Session, workspace: Service):
    return perform(lambda: read(request, session, workspace, body))
