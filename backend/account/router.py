"""Same-origin profile reads/edits expose separately computed action capabilities."""

import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from account import repository
from account.availability import capabilities
from account.contracts import ProfileUpdate
from auth.security import UserSession, get_store, require_user
from auth.store import IdentityStore
from workspace.database import admit, guard
from workspace.dependencies import perform
from workspace.errors import WorkspaceError

router = APIRouter(prefix="/api/v1/me", tags=["private account"])
Session = Annotated[UserSession, Depends(require_user)]
Store = Annotated[IdentityStore, Depends(get_store)]


def account_request(
    request: Request,
    session: UserSession,
    store: IdentityStore,
    operation: str,
    body: ProfileUpdate | None = None,
) -> dict:
    if request.query_params:
        raise WorkspaceError("invalid_request", 422)
    # Reads and failed CAS writes share the existing durable account budget.
    # GET authentication and these transactions do not refresh idle/freshness.
    with store.storage.transaction() as conn:
        guard(conn, session, store.policy)
        admit(conn, session.user["id"])
    with store.storage.transaction() as conn:
        guard(conn, session, store.policy)
        available = capabilities(
            conn,
            session.user["id"],
            request.app.state.settings.app_origin,
            google_enabled=bool(request.app.state.settings.google_client_id),
        )
        if operation == "profile":
            result = repository.profile(conn, session.user["id"])
        elif operation == "save" and body is not None:
            result = repository.save_profile(conn, session.user["id"], body)
        elif operation == "methods":
            result = repository.methods(
                conn,
                session.user["id"],
                password_enabled=os.environ.get("PASSWORD_AUTH_ENABLED", "false")
                == "true",
                google_enabled=bool(request.app.state.settings.google_client_id),
            )
        elif operation == "sessions":
            result = repository.sessions(conn, session)
            result["capabilities"] = {
                "revoke_one": available["session_revoke"],
                "revoke_all": available["sessions_revoke_all"],
            }
            return result
        else:
            raise ValueError("account_operation_invalid")
        return {**result, "capabilities": available}


@router.get("")
def read_account(request: Request, session: Session, store: Store) -> Any:
    return perform(lambda: account_request(request, session, store, "profile"))


@router.patch("")
def update_profile(
    body: ProfileUpdate, request: Request, session: Session, store: Store
) -> Any:
    return perform(lambda: account_request(request, session, store, "save", body))


@router.get("/methods")
def read_methods(request: Request, session: Session, store: Store) -> Any:
    return perform(lambda: account_request(request, session, store, "methods"))


@router.get("/sessions")
def read_sessions(request: Request, session: Session, store: Store) -> Any:
    return perform(lambda: account_request(request, session, store, "sessions"))
