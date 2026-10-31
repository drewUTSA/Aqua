"""Only explicit owned export actions cross this private HTTP boundary."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from account.identity_runtime import get_identity_passwords
from account.security_http import perform
from auth.passwords import PasswordStore
from auth.security import UserSession, require_user
from privacy.contracts import ExportCreate, ExportReviewQuery
from privacy.dependencies import Service, download_session
from privacy.policy import identifier
from workspace.dependencies import perform as read_perform
from workspace.errors import WorkspaceError

router = APIRouter(prefix="/api/v1/me/data-exports", tags=["private export"])
Session = Annotated[UserSession, Depends(require_user)]
Passwords = Annotated[PasswordStore, Depends(get_identity_passwords)]
DownloadSession = Annotated[UserSession, Depends(download_session)]


def closed_query(request):
    if request.query_params:
        raise WorkspaceError("invalid_request", 422)


def selected(value):
    try:
        return identifier(value)
    except ValueError:
        raise WorkspaceError("not_found") from None


@router.post("")
def create(
    body: ExportCreate,
    request: Request,
    session: Session,
    passwords: Passwords,
    service: Service,
):
    def work():
        closed_query(request)
        result, status = service.create(session, body, passwords)
        return JSONResponse(result, status_code=status)

    return perform("data_export", work)


@router.get("")
def listing(request: Request, session: Session, service: Service):
    def work():
        if (
            set(request.query_params) - {"cursor"}
            or len(request.query_params.getlist("cursor")) > 1
        ):
            raise WorkspaceError("invalid_request", 422)
        try:
            query = ExportReviewQuery.model_validate(dict(request.query_params))
        except ValueError:
            raise WorkspaceError("invalid_cursor", 422) from None
        return service.listing(session, query.cursor)

    return read_perform(work)


@router.get("/by-intent/{intent_id}")
def by_intent(intent_id: str, request: Request, session: Session, service: Service):
    def work():
        closed_query(request)
        return service.status(session, intent_id=selected(intent_id))

    return read_perform(work)


@router.get("/{job_id}")
def status(job_id: str, request: Request, session: Session, service: Service):
    def work():
        closed_query(request)
        return service.status(session, job_id=selected(job_id))

    return read_perform(work)


@router.get("/{job_id}/download")
async def download(
    job_id: str, request: Request, session: DownloadSession, service: Service
):
    from privacy.download import response
    from storage.pool import StorageUnavailable
    from workspace.errors import failure

    try:
        closed_query(request)
        return await response(request, session, service, selected(job_id))
    except WorkspaceError as error:
        return failure(error)
    except StorageUnavailable:
        return failure(WorkspaceError("service_unavailable", 503))
