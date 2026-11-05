"""Private cache headers without decoupling physical ASGI send ownership."""

from starlette.datastructures import MutableHeaders


class PrivateAPIResponses:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            await self.app(scope, receive, send)
            return

        async def private_send(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
                vary = headers.get("Vary", "")
                if "cookie" not in {part.strip().lower() for part in vary.split(",")}:
                    headers["Vary"] = f"{vary}, Cookie" if vary else "Cookie"
            # Await the original send directly. No intermediate response/body
            # channel may release a worker/download physical slot prematurely.
            await send(message)

        await self.app(scope, receive, private_send)
