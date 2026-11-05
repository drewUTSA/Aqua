"""Account preferences never depend on or change analytical dataset authority."""

from typing import Any, Annotated
from fastapi import APIRouter, Depends, Request
from auth.security import UserSession, get_store, require_user
from auth.store import IdentityStore
from preferences import repository
from preferences.contracts import PreferenceUpdate
from workspace.database import admit, guard
from workspace.dependencies import perform
from workspace.errors import WorkspaceError

router = APIRouter(prefix="/api/v1/me/preferences", tags=["private preferences"])
Session = Annotated[UserSession, Depends(require_user)]
Store = Annotated[IdentityStore, Depends(get_store)]


def apply(
    request: Request,
    session: UserSession,
    store: IdentityStore,
    body: PreferenceUpdate | None = None,
) -> dict:
    if request.query_params:
        raise WorkspaceError("invalid_request", 422)
    # Reuse the durable 60/account/minute workspace budget across sessions and
    # processes. Admission commits separately so stale revisions cannot evade it.
    with store.storage.transaction() as conn:
        guard(conn, session, store.policy)
        admit(conn, session.user["id"])
    with store.storage.transaction() as conn:
        guard(conn, session, store.policy)
        result = (
            repository.read(conn, session.user["id"])
            if body is None
            else repository.save(conn, session.user["id"], body)
        )
        privacy = getattr(request.app.state, "privacy", None)
        result["capabilities"]["private_data_export"] = bool(
            privacy is not None
            and privacy.storage is store.storage
            and privacy.settings == request.app.state.settings
            and privacy.capable(conn)
        )
        return result


@router.get("")
def read_preferences(request: Request, session: Session, store: Store) -> Any:
    return perform(lambda: apply(request, session, store))


@router.put("")
def save_preferences(
    body: PreferenceUpdate, request: Request, session: Session, store: Store
) -> Any:
    return perform(lambda: apply(request, session, store, body))
