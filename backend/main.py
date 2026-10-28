"""HTTP routes. All the work happens in nl2sql.pipeline; this file only
turns requests into pipeline calls and pipeline results into JSON."""

import logging
from contextlib import asynccontextmanager
from collections.abc import Awaitable, Callable, AsyncIterator
from typing import Any, Literal, Self

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse, Response
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, model_validator

from auth.router import router as auth_router
from auth.password_router import router as password_router
from auth.security import UserSession, require_database_access
from nl2sql.cache import AnswerCache
from nl2sql.config import Settings, load_settings
from nl2sql.pipeline import Retriever, answer_question
from nl2sql.schema import get_schema

from storage.config import load_storage_settings
from storage.pool import Storage
from storage.readiness import router as readiness_router
from workspace.router import router as workspace_router
from workspace.errors import WorkspaceError, failure as workspace_failure
from workspace.boundary import PREFIXES as WORKSPACE_PREFIXES, WorkspaceBodyLimit
from workspace.access_logging import install as private_workspace_access_logging
from analysis.router import router as analysis_router
from preferences.router import router as preferences_router
from analysis.dependencies import get_analysis
from analysis.service import Analysis
from nl2sql.query_service import run as run_query
from storage.pool import StorageUnavailable


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.storage.open()
    service = getattr(app.state, "analysis", None)
    if service is None and app.state.storage.settings.enabled:
        from auth.config import load_auth_policy

        configured = app.state.settings
        # The dispatcher checks schema readiness and retries independently.
        # A storage outage must not prevent the liveness route from starting.
        if len(configured.session_secret) >= 32:
            service = Analysis(
                app.state.storage,
                load_auth_policy(configured),
                configured.session_secret,
                configured,
            )
            app.state.analysis = service
    if service is not None:
        service.start()
    try:
        yield
    finally:
        service = getattr(app.state, "analysis", None)
        if service is not None:
            service.close()
            app.state.analysis = None
        app.state.storage.close()


app = FastAPI(title="Aqua", lifespan=lifespan)
private_workspace_access_logging()
log = logging.getLogger("aqua")

SETTINGS = load_settings()
app.state.settings = SETTINGS
app.include_router(auth_router)
app.include_router(password_router)
app.include_router(readiness_router)
app.include_router(workspace_router)
app.include_router(analysis_router)
app.include_router(preferences_router)
app.state.storage = Storage(load_storage_settings())
app.add_middleware(WorkspaceBodyLimit)


@app.exception_handler(HTTPException)
async def safe_workspace_http_error(request: Request, error: HTTPException) -> Response:
    if request.url.path.startswith(WORKSPACE_PREFIXES):
        code = {
            401: "session_invalid",
            403: "access_denied",
            503: "service_unavailable",
        }.get(error.status_code, "invalid_request")
        return workspace_failure(WorkspaceError(code, error.status_code))
    return await http_exception_handler(request, error)


@app.exception_handler(RequestValidationError)
async def safe_request_validation(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    """Validation errors must not reflect credentials or private prompts."""
    if request.url.path.startswith(
        (
            "/api/v1/chats",
            "/api/v1/analysis-requests",
            "/api/v1/projects",
            "/api/v1/me/saved-prompts",
            "/api/v1/me/preferences",
            "/api/v1/starter-prompts",
        )
    ):
        return workspace_failure(WorkspaceError("invalid_request", 422))
    return JSONResponse(
        status_code=422, content={"detail": "Request could not be validated."}
    )


@app.middleware("http")
async def private_api_responses(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Keep identity and customer query results out of shared HTTP caches."""
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        vary = response.headers.get("Vary", "")
        if "cookie" not in {part.strip().lower() for part in vary.split(",")}:
            response.headers["Vary"] = f"{vary}, Cookie" if vary else "Cookie"
    return response


def _retriever(settings: Settings | None = None) -> Retriever | None:
    """The vector retriever when RETRIEVAL is on, otherwise None.

    Imported only when on, so the app starts without the embedding SDK
    configured. If retrieval fails at question time, the pipeline falls
    back to the full schema.
    """
    settings = SETTINGS if settings is None else settings
    if not settings.retrieval:
        return None
    from nl2sql.retrieval.select import VectorRetriever

    return VectorRetriever(settings)


RETRIEVER = _retriever()

# Recent successful answers, reused for the same question and model
# (ANSWER_CACHE_SECONDS; 0 turns it off). See nl2sql/cache.py.
ANSWER_CACHE = AnswerCache(SETTINGS.answer_cache_seconds)


def _model_name(provider: str, settings: Settings | None = None) -> str:
    settings = SETTINGS if settings is None else settings
    return settings.gemini_model if provider == "gemini" else settings.ollama_model


def available_models() -> list[dict[str, str]]:
    """The models this server can run, default first.

    Same shape as the frontend's model list, so its dropdown can be
    filled from here. Gemini is listed only when a key is set, so the
    UI never offers a choice that would fail.
    """
    models = {
        "ollama": {
            "id": "ollama",
            "name": SETTINGS.ollama_model,
            "description": "Open model on the team server",
        }
    }
    if SETTINGS.gemini_api_key:
        models["gemini"] = {
            "id": "gemini",
            "name": SETTINGS.gemini_model,
            "description": "Google Gemini API",
        }
    default = models.pop(SETTINGS.llm_provider, None)
    return ([default] if default else []) + list(models.values())


@app.get("/api/health")
def health():
    """Liveness for the Docker healthcheck. Never touches the database or
    model, so a slow dependency cannot mark the container unhealthy."""
    return {
        "status": "ok",
        "database_configured": bool(SETTINGS.database_url),
        "model": _model_name(SETTINGS.llm_provider),
        "retrieval": SETTINGS.retrieval,
    }


@app.get("/api/models")
def models():
    """The model choices for the frontend's dropdown."""
    return {"models": available_models()}


class QueryRequest(BaseModel):
    # Whitespace is trimmed first, so a blank question fails min_length
    # and FastAPI answers 422 before the model is called.
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    # An id from /api/models. Left out, the server default (LLM_PROVIDER)
    # is used; anything else is a 422.
    model: Literal["ollama", "gemini"] | None = None

    @model_validator(mode="after")
    def safe_text(self) -> Self:
        if "\x00" in self.question:
            raise ValueError("query_text_invalid")
        try:
            self.question.encode("utf-8")
        except UnicodeError:
            raise ValueError("query_text_invalid") from None
        return self


@app.post("/api/query", response_model=None)
def query(
    body: QueryRequest,
    session: UserSession = Depends(require_database_access),
    service: Analysis = Depends(get_analysis),
) -> dict[str, Any] | JSONResponse:
    """Legacy final JSON uses the same durable admission/deadline supervisor."""
    try:
        result, status = service.legacy(session, body.question, body.model)
    except WorkspaceError as error:
        return workspace_failure(error)
    except StorageUnavailable:
        return workspace_failure(WorkspaceError("service_unavailable", 503))
    return result if status == 200 else JSONResponse(status_code=status, content=result)


def workspace_query(
    question: str, model: str, session: UserSession, configured: Settings
) -> dict[str, Any] | JSONResponse:
    """Pure safety-service seam for offline contract tests; never an HTTP bypass."""
    result, status = run_query(
        question,
        model,
        configured,
        session.user["id"],
        session.grant_version,
        session.auth_epoch,
        cache=ANSWER_CACHE,
        schema_reader=get_schema,
        answerer=answer_question,
        retriever_factory=_retriever,
    )
    return result if status == 200 else JSONResponse(status_code=status, content=result)


app.state.workspace_query = workspace_query
