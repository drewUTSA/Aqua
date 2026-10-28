"""Allow only the phase's private API routes in the network-none bridge."""

import re
from urllib.parse import parse_qsl, urlsplit

UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
ROUTES = (
    (r"/api/v1/me", {"GET": set(), "PATCH": set()}),
    (r"/api/v1/me/(methods|sessions)", {"GET": set()}),
    (r"/api/v1/me/preferences", {"GET": set(), "PUT": set()}),
    (
        r"/api/v1/chats",
        {"GET": {"cursor", "limit", "archived", "project_id"}, "POST": set()},
    ),
    (r"/api/v1/chats/search", {"POST": set()}),
    (rf"/api/v1/chats/{UUID}", {"GET": set(), "PATCH": set(), "DELETE": {"revision"}}),
    (rf"/api/v1/chats/{UUID}/messages", {"GET": {"cursor", "limit"}, "POST": set()}),
    (rf"/api/v1/chats/{UUID}/messages/{UUID}/retries", {"POST": set()}),
    (rf"/api/v1/analysis-requests/{UUID}", {"GET": set()}),
    (rf"/api/v1/analysis-requests/{UUID}/cancel", {"POST": set()}),
    (rf"/api/v1/analysis-requests/{UUID}/events", {"GET": set()}),
    (r"/api/v1/projects", {"GET": {"cursor", "limit", "archived"}, "POST": set()}),
    (rf"/api/v1/projects/{UUID}", {"PATCH": set(), "DELETE": {"revision"}}),
    (r"/api/v1/me/saved-prompts", {"GET": {"cursor", "limit"}, "POST": set()}),
    (rf"/api/v1/me/saved-prompts/{UUID}", {"PATCH": set(), "DELETE": {"revision"}}),
    (rf"/api/v1/me/saved-prompts/{UUID}/uses", {"POST": set()}),
    (r"/api/v1/starter-prompts", {"GET": set()}),
)


def workspace_route(path: str, method: str) -> bool:
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        return False
    try:
        query = parse_qsl(
            parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=6
        )
    except ValueError:
        return False
    if len({key for key, _ in query}) != len(query) or any(
        len(value) > 1024 for _, value in query
    ):
        return False
    for pattern, methods in ROUTES:
        if re.fullmatch(pattern, parsed.path):
            return method in methods and all(key in methods[method] for key, _ in query)
    return False
