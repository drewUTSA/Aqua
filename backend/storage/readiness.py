"""Readiness is distinct from cheap liveness and reveals no account data."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from storage.pool import StorageUnavailable

router = APIRouter()


@router.get("/api/ready")
def ready(request: Request):
    try:
        return request.app.state.storage.readiness()
    except StorageUnavailable:
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "application_storage": "unavailable"},
        )
