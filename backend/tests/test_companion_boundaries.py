"""Private backend delivery guards for the new application path."""

import logging

from workspace.access_logging import PrivateWorkspaceAccess
from workspace.boundary import PREFIXES


def test_companion_private_paths_suppress_canaries_in_backend_access_logs():
    assert "/api/v1/companion" in PREFIXES
    for path in (
        "/api/v1/companion/help?question=PRIVATE-CANARY",
        "/api/v1/companion/capabilities?owner=PRIVATE-CANARY",
    ):
        record = logging.LogRecord(
            "uvicorn.access",
            logging.INFO,
            "fixture",
            1,
            "%s %s %s %s %s",
            ("peer", "GET", path, "1.1", 200),
            None,
        )
        assert not PrivateWorkspaceAccess().filter(record)
