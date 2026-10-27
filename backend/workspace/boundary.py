"""Cap JSON bytes before FastAPI parses a workspace mutation body."""

from workspace.errors import WorkspaceError, failure
from starlette.types import ASGIApp, Message, Receive, Scope, Send

PREFIXES = (
    "/api/v1/analysis-requests",
    "/api/v1/chats",
    "/api/v1/projects",
    "/api/v1/me/saved-prompts",
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
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            chunk = event.get("body", b"")
            if len(body) + len(chunk) > 16384:
                await failure(WorkspaceError("invalid_request", 413))(
                    scope, receive, send
                )
                return
            body.extend(chunk)
            if not event.get("more_body", False):
                break
        delivered = False

        async def bounded_receive() -> Message:
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, bounded_receive, send)
