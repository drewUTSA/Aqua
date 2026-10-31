"""Fixed private action errors and host-bound browser challenge cookies."""

from collections.abc import Callable
import logging
from typing import Any

from auth.config import AuthDenied, AuthLimited
from auth.mailconfig import MailUnavailable
from nl2sql.config import Settings
from storage.pool import StorageUnavailable
from workspace.errors import WorkspaceError, failure

log = logging.getLogger("aqua.account_security")


def binding_cookie(settings: Settings) -> str:
    prefix = "__Host-" if settings.app_origin.startswith("https://") else ""
    return prefix + "aqua_account_action"


def identity_cookie(settings: Settings) -> str:
    prefix = "__Host-" if settings.app_origin.startswith("https://") else ""
    return prefix + "aqua_identity_action"


def perform(action: str, work: Callable[[], Any]) -> Any:
    try:
        return work()
    except WorkspaceError as error:
        log.warning("account_security_event action=%s reason=denied", action)
        return failure(error)
    except AuthLimited as error:
        log.warning("account_security_event action=%s reason=rate_limited", action)
        response = failure(WorkspaceError("rate_limited", 429))
        response.headers["Retry-After"] = str(error.retry_after)
        return response
    except (StorageUnavailable, MailUnavailable, AuthDenied):
        log.warning("account_security_event action=%s reason=unavailable", action)
        return failure(WorkspaceError("security_unavailable", 503))
