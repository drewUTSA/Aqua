"""Shared safe HTTP dependencies for private workspace routers."""

from collections.abc import Callable
from typing import Annotated, Any
from fastapi import Depends, Query
from auth.security import UserSession, get_settings, get_store, require_user
from auth.store import IdentityStore
from nl2sql.config import Settings
from storage.pool import StorageUnavailable
from workspace.errors import WorkspaceError, failure
from workspace.service import Workspace

Session = Annotated[UserSession, Depends(require_user)]
Page = Annotated[int, Query(ge=1, le=100)]
Revision = Annotated[int, Query(ge=1)]


def get_workspace(
    settings: Annotated[Settings, Depends(get_settings)],
    store: Annotated[IdentityStore, Depends(get_store)],
) -> Workspace:
    return Workspace(store.storage, store.policy, settings.session_secret)


Service = Annotated[Workspace, Depends(get_workspace)]


def perform(callback: Callable[[], Any]) -> Any:
    try:
        return callback()
    except WorkspaceError as error:
        return failure(error)
    except StorageUnavailable:
        return failure(WorkspaceError("service_unavailable", 503))
