"""Keep private title-search input and opaque cursors out of HTTP access logs."""

import logging

from workspace.boundary import PREFIXES


class PrivateWorkspaceAccess(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # The pinned Uvicorn access logger passes peer/method/target/version/status.
        # Unknown formats fail closed here; fixed application/security events
        # use other loggers and retain their ordinary behavior.
        arguments = record.args
        if (
            not isinstance(arguments, tuple)
            or len(arguments) != 5
            or not isinstance(arguments[2], str)
        ):
            return False
        return not arguments[2].split("?", 1)[0].startswith(PREFIXES)


def install() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, PrivateWorkspaceAccess) for item in logger.filters):
        logger.addFilter(PrivateWorkspaceAccess())
