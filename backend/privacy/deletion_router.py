"""Explicit destructive operations and a closed, purpose-only receipt route."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from account.identity_runtime import get_identity_passwords
from account.security_http import perform
from auth.passwords import PasswordStore
from privacy.deletion_contracts import DeletionCreate
from privacy.deletion_dependencies import Bearer, Service
from retirement.deletion_policy import RECEIPT_HEADER, receipt_digest
from retirement.fingerprints import canonical_uuid
from retirement.interlock import RetirementUnavailable
from workspace.errors import WorkspaceError

router = APIRouter(prefix="/api/v1/me/data-deletions", tags=["private deletion"])
Passwords = Annotated[PasswordStore, Depends(get_identity_passwords)]


class ReceiptRead(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def guarded(work):
    def safe():
        try:
            return work()
        except RetirementUnavailable:
            raise WorkspaceError("service_unavailable", 503) from None

    return perform("data_delete", safe)


@router.post("")
def create(
    body: DeletionCreate, bearer: Bearer, passwords: Passwords, service: Service
):
    def work():
        result, status = service.create(bearer, body, passwords)
        return JSONResponse(result, status_code=status)

    return guarded(work)


@router.post("/by-intent/{intent_id}")
def by_intent(
    intent_id: str,
    body: ReceiptRead,
    request: Request,
    bearer: Bearer,
    service: Service,
):
    def work():
        try:
            intent = canonical_uuid(intent_id)
            receipt = request.headers.get(RECEIPT_HEADER)
            receipt_digest(receipt)
        except ValueError:
            raise WorkspaceError("not_found") from None
        return service.status(bearer, intent, receipt)

    return guarded(work)
