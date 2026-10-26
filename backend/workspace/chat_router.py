"""Owned chats and server-authored synchronous submissions."""

from typing import Annotated
from uuid import UUID
from typing import Any
from pydantic import BaseModel
from fastapi import APIRouter, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from auth.security import UserSession, get_settings
from workspace import history
from workspace.contracts import (
    ChatPatch,
    ChatSearch,
    FirstSubmission,
    RequestKey,
    Submission,
)
from workspace.dependencies import Session, Service, Page, Revision, perform
from workspace.service import Workspace
from workspace.errors import WorkspaceError, failure

router = APIRouter()


@router.get("/chats")
def chats(
    request: Request,
    session: Session,
    service: Service,
    limit: Page = 20,
    cursor: str | None = None,
    archived: bool = False,
    project_id: UUID | None = None,
) -> Any:
    if "search" in request.query_params:
        return failure(WorkspaceError("invalid_request", 422))
    return perform(
        lambda: service.apply(
            session,
            lambda conn, current: history.list_chats(
                conn,
                current,
                service.secret,
                limit=limit,
                cursor=cursor,
                search="",
                archived=archived,
                project_id=str(project_id) if project_id else None,
            ),
        )
    )


@router.post("/chats/search")
def search_chats(body: ChatSearch, session: Session, service: Service) -> Any:
    return perform(
        lambda: service.apply(
            session,
            lambda conn, current: history.list_chats(
                conn,
                current,
                service.secret,
                limit=body.limit,
                cursor=body.cursor,
                search=body.search,
                archived=body.archived,
                project_id=str(body.project_id) if body.project_id else None,
            ),
        )
    )


@router.get("/chats/{chat_id}")
def chat(chat_id: UUID, session: Session, service: Service) -> Any:
    return perform(
        lambda: service.apply(
            session,
            lambda conn, current: {
                "chat": history.public(
                    history.chat_row(conn, current.user["id"], str(chat_id))
                )
            },
        )
    )


@router.get("/chats/{chat_id}/messages")
def messages(
    chat_id: UUID,
    session: Session,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: str | None = None,
) -> Any:
    return perform(
        lambda: service.apply(
            session,
            lambda conn, current: history.message_rows(
                conn,
                current.user["id"],
                str(chat_id),
                current,
                service.policy,
                limit=limit,
                cursor=cursor,
                secret=service.secret,
            ),
        )
    )


def submit(
    request: Request,
    session: UserSession,
    service: Workspace,
    body: BaseModel,
    chat_id: str | None = None,
    input_id: str | None = None,
) -> Any:
    def run():
        result, status = service.submit(
            session,
            body,
            request.app.state.workspace_query,
            get_settings(request),
            chat_id=chat_id,
            input_id=input_id,
        )
        return JSONResponse(jsonable_encoder(result), status_code=status)

    return perform(run)


@router.post("/chats")
def first_message(
    body: FirstSubmission, request: Request, session: Session, service: Service
) -> Any:
    return submit(request, session, service, body)


@router.post("/chats/{chat_id}/messages")
def append_message(
    chat_id: UUID,
    body: Submission,
    request: Request,
    session: Session,
    service: Service,
) -> Any:
    return submit(request, session, service, body, str(chat_id))


@router.post("/chats/{chat_id}/messages/{input_id}/retries")
def retry_message(
    chat_id: UUID,
    input_id: UUID,
    body: RequestKey,
    request: Request,
    session: Session,
    service: Service,
) -> Any:
    return submit(request, session, service, body, str(chat_id), str(input_id))


@router.patch("/chats/{chat_id}")
def update_chat(
    chat_id: UUID, body: ChatPatch, session: Session, service: Service
) -> Any:
    return perform(
        lambda: service.apply(
            session,
            lambda conn, current: history.patch_chat(
                conn, current.user["id"], str(chat_id), body
            ),
            mutate=True,
        )
    )


@router.delete("/chats/{chat_id}", status_code=204)
def remove_chat(
    chat_id: UUID, session: Session, service: Service, revision: Revision
) -> Response:
    result = perform(
        lambda: service.apply(
            session,
            lambda conn, current: history.delete_chat(
                conn, current.user["id"], str(chat_id), revision
            ),
            mutate=True,
        )
    )
    return result if isinstance(result, JSONResponse) else Response(status_code=204)
