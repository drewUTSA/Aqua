"""Private projects and saved prompts, separate from curated examples."""

from uuid import UUID
from typing import Any
from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from workspace import catalog
from workspace.contracts import (
    ProjectCreate,
    ProjectPatch,
    PromptCreate,
    PromptPatch,
    RequestKey,
)
from workspace.dependencies import Session, Service, Page, Revision, perform

router = APIRouter()


@router.get("/projects")
def projects(
    session: Session,
    service: Service,
    limit: Page = 20,
    cursor: str | None = None,
    archived: bool = False,
) -> Any:
    return perform(
        lambda: service.apply(
            session,
            lambda conn, current: catalog.listing(
                conn,
                "projects",
                current.user["id"],
                service.secret,
                limit=limit,
                cursor=cursor,
                archived=archived,
            ),
        )
    )


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate, session: Session, service: Service) -> Any:
    return perform(
        lambda: service.apply(
            session,
            lambda conn, current: catalog.create(
                conn, "projects", current.user["id"], body
            ),
            mutate=True,
        )
    )


@router.patch("/projects/{item_id}")
def update_project(
    item_id: UUID, body: ProjectPatch, session: Session, service: Service
) -> Any:
    return perform(
        lambda: service.apply(
            session,
            lambda conn, current: catalog.patch(
                conn, "projects", current.user["id"], str(item_id), body
            ),
            mutate=True,
        )
    )


@router.delete("/projects/{item_id}", status_code=204)
def remove_project(
    item_id: UUID, session: Session, service: Service, revision: Revision
) -> Response:
    result = perform(
        lambda: service.apply(
            session,
            lambda conn, current: catalog.delete(
                conn, "projects", current.user["id"], str(item_id), revision
            ),
            mutate=True,
        )
    )
    return result if isinstance(result, JSONResponse) else Response(status_code=204)


@router.get("/me/saved-prompts")
def prompts(
    session: Session, service: Service, limit: Page = 20, cursor: str | None = None
) -> Any:
    return perform(
        lambda: service.apply(
            session,
            lambda conn, current: catalog.listing(
                conn,
                "saved_prompts",
                current.user["id"],
                service.secret,
                limit=limit,
                cursor=cursor,
            ),
        )
    )


@router.post("/me/saved-prompts", status_code=201)
def create_prompt(body: PromptCreate, session: Session, service: Service) -> Any:
    return perform(
        lambda: service.apply(
            session,
            lambda conn, current: catalog.create(
                conn, "saved_prompts", current.user["id"], body
            ),
            mutate=True,
        )
    )


@router.patch("/me/saved-prompts/{item_id}")
def update_prompt(
    item_id: UUID, body: PromptPatch, session: Session, service: Service
) -> Any:
    return perform(
        lambda: service.apply(
            session,
            lambda conn, current: catalog.patch(
                conn, "saved_prompts", current.user["id"], str(item_id), body
            ),
            mutate=True,
        )
    )


@router.delete("/me/saved-prompts/{item_id}", status_code=204)
def remove_prompt(
    item_id: UUID, session: Session, service: Service, revision: Revision
) -> Response:
    result = perform(
        lambda: service.apply(
            session,
            lambda conn, current: catalog.delete(
                conn, "saved_prompts", current.user["id"], str(item_id), revision
            ),
            mutate=True,
        )
    )
    return result if isinstance(result, JSONResponse) else Response(status_code=204)


@router.post("/me/saved-prompts/{item_id}/uses")
def use_prompt(
    item_id: UUID, body: RequestKey, session: Session, service: Service
) -> Any:
    return perform(
        lambda: service.apply(
            session,
            lambda conn, current: catalog.use_prompt(
                conn, current.user["id"], str(item_id), body.client_request_id
            ),
            mutate=True,
        )
    )


@router.get("/starter-prompts")
def starter_prompts(session: Session) -> Any:
    return {"items": catalog.STARTERS}
