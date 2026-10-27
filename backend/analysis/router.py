"""Owned request status/cancellation; progress transport contains metadata only."""

from uuid import UUID
from typing import Any
from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from workspace.contracts import StrictBody
from workspace.dependencies import Session, perform
from analysis.dependencies import Service

router = APIRouter(prefix="/api/v1/analysis-requests")


@router.get("/{request_id}")
def status(request_id: UUID, session: Session, service: Service) -> Any:
    return perform(
        lambda: JSONResponse(
            jsonable_encoder(service.snapshot(session, str(request_id)))
        )
    )


@router.post("/{request_id}/cancel")
def cancel(request_id: UUID, body: StrictBody, session: Session, service: Service):
    def run():
        saved, code = service.cancel(session, str(request_id))
        return JSONResponse(jsonable_encoder(saved), status_code=code)

    return perform(run)


@router.get("/{request_id}/events")
def stream(request_id: UUID, request: Request, session: Session, service: Service):
    from analysis.streams import response

    return perform(lambda: response(request, session, service, str(request_id)))
