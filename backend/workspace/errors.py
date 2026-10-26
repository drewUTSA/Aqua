"""Fixed safe failures never include private driver/provider diagnostics."""

from dataclasses import dataclass
from uuid import uuid4

from fastapi.responses import JSONResponse


@dataclass
class WorkspaceError(Exception):
    code: str
    status: int = 404


MESSAGES = {
    "session_invalid": "Sign in to continue.",
    "retry_unavailable": "This saved answer cannot be retried. Check its current state.",
    "chat_archived": "Unarchive this chat before adding another message.",
    "not_found": "This workspace item is unavailable.",
    "revision_conflict": "This item changed. Reload it before trying again.",
    "idempotency_conflict": "This request identifier was already used for different input.",
    "invalid_cursor": "This page cursor is invalid or belongs to another list.",
    "capacity_reached": "This workspace has reached its current storage limit.",
    "rate_limited": "Too many workspace changes. Wait a minute and try again.",
    "access_denied": "This account cannot access the requested analytical data.",
    "service_unavailable": "The workspace is temporarily unavailable.",
    "invalid_request": "This workspace request could not be validated.",
}


def failure(error: WorkspaceError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status,
        content={
            "error": {
                "code": error.code,
                "message": MESSAGES.get(error.code, MESSAGES["invalid_request"]),
                "request_id": str(uuid4()),
            }
        },
        headers={
            "Cache-Control": "no-store",
            **({"Retry-After": "60"} if error.status == 429 else {}),
        },
    )
