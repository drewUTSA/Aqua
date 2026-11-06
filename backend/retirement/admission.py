"""A failed restore admission leaves cheap liveness available and writers shut."""

from starlette.responses import JSONResponse


class RetirementAdmission:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        runtime = getattr(getattr(scope.get("app"), "state", None), "retirement", None)
        if (
            scope["type"] == "http"
            and runtime is not None
            and not runtime.ready
            and scope.get("path", "").startswith("/api/")
            and scope.get("path") not in {"/api/health", "/api/ready"}
        ):
            await JSONResponse(
                {"error": {"code": "service_unavailable"}}, status_code=503
            )(scope, receive, send)
            return
        await self.app(scope, receive, send)
