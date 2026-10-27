"""One bounded dispatcher per app; fixture injection is an explicit Python seam."""

import threading
from typing import Annotated
from fastapi import Depends, Request
from auth.security import get_settings, get_store
from auth.store import IdentityStore
from nl2sql.config import Settings
from analysis.service import Analysis

LOCK = threading.Lock()


def get_analysis(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    store: Annotated[IdentityStore, Depends(get_store)],
) -> Analysis:
    with LOCK:
        current = getattr(request.app.state, "analysis", None)
        if (
            current is not None
            and current.storage is store.storage
            and current.settings == settings
        ):
            return current
        if current is not None:
            current.close()
        current = Analysis(
            store.storage, store.policy, settings.session_secret, settings, start=True
        )
        request.app.state.analysis = current
        return current


Service = Annotated[Analysis, Depends(get_analysis)]
