"""Cap JSON bytes before FastAPI parses a workspace mutation body."""

import json
from workspace.errors import WorkspaceError, failure
from starlette.types import ASGIApp, Message, Receive, Scope, Send

PREFIXES = (
    "/api/v1/analysis-requests",
    "/api/v1/chats",
    "/api/v1/projects",
    "/api/v1/me/saved-prompts",
    "/api/v1/me/preferences",
    "/api/v1/starter-prompts",
)


class WorkspaceBodyLimit:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or not scope.get("path", "").startswith((*PREFIXES, "/api/query"))
            or scope["method"] not in {"POST", "PATCH", "PUT"}
        ):
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        if (
            headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower()
            != b"application/json"
        ):
            await failure(WorkspaceError("invalid_request", 415))(scope, receive, send)
            return
        body = bytearray()
        limit = (
            65536
            if scope.get("path", "").startswith("/api/v1/me/preferences")
            else 16384
        )
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            chunk = event.get("body", b"")
            if len(body) + len(chunk) > limit:
                await failure(WorkspaceError("invalid_request", 413))(
                    scope, receive, send
                )
                return
            body.extend(chunk)
            if not event.get("more_body", False):
                break
        delivered = False
        if scope.get("path", "").startswith("/api/v1/me/preferences"):
            try:
                json.loads(body, object_pairs_hook=unique_object)
            except (ValueError, UnicodeError, RecursionError):
                await failure(WorkspaceError("invalid_request", 422))(
                    scope, receive, send
                )
                return

        async def bounded_receive() -> Message:
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, bounded_receive, send)


def unique_object(pairs: list[tuple]) -> dict:
    """Ambiguous duplicate keys must not acquire last-wins save semantics."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_preference_key")
        result[key] = value
    return result
