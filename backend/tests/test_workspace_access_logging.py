"""Private search/cursor canaries never reach HTTP access-log formatting."""

import logging

from workspace.access_logging import PrivateWorkspaceAccess, install


def record(path: str) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "fixture",
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("fixture-peer", "GET", path, "1.1", 200),
        None,
    )


def test_private_workspace_access_records_are_suppressed_without_changing_health():
    filter = PrivateWorkspaceAccess()
    canary = "PRIVATE_TITLE_SEARCH_CANARY"
    for path in [
        "/api/v1/chats?search=" + canary,
        "/api/v1/projects?cursor=" + canary,
        "/api/v1/me/saved-prompts?cursor=" + canary,
        "/api/v1/me?name=" + canary,
        "/api/v1/me/methods?owner_id=" + canary,
        "/api/v1/me/sessions/" + canary,
    ]:
        assert not filter.filter(record(path))
    assert filter.filter(record("/api/health"))
    assert filter.filter(record("/api/models"))
    assert not filter.filter(
        logging.LogRecord(
            "uvicorn.access", logging.INFO, "fixture", 1, canary, (), None
        )
    )


def test_access_filter_installation_is_repeatable_and_keeps_application_events():
    install()
    install()
    access = logging.getLogger("uvicorn.access")
    assert (
        len(
            [
                item
                for item in access.filters
                if isinstance(item, PrivateWorkspaceAccess)
            ]
        )
        == 1
    )
    event = logging.getLogger("aqua.workspace")
    assert not any(isinstance(item, PrivateWorkspaceAccess) for item in event.filters)
