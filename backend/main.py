"""HTTP routes. All the work happens in nl2sql.pipeline; this file only
turns requests into pipeline calls and pipeline results into JSON."""

import logging
from contextlib import asynccontextmanager
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse, Response
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field

from auth.router import router as auth_router
from auth.password_router import router as password_router
from auth.security import UserSession, get_settings, require_database_access
from nl2sql.cache import AnswerCache, scoped_cache_key
from nl2sql.cache_scope import request_scope
from nl2sql.errors import ContextDenied
from nl2sql.config import Settings, load_settings
from nl2sql.db import DatabaseError
from nl2sql.display import display_for
from nl2sql.llm import LLMError
from nl2sql.pipeline import Retriever, answer_question
from nl2sql.response import outage_response, to_response
from nl2sql.schema import get_schema

from storage.config import load_storage_settings
from storage.pool import Storage
from storage.readiness import router as readiness_router
from workspace.router import router as workspace_router
from workspace.errors import WorkspaceError, failure as workspace_failure
from workspace.boundary import PREFIXES as WORKSPACE_PREFIXES, WorkspaceBodyLimit
from workspace.access_logging import install as private_workspace_access_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.storage.open()
    try:
        yield
    finally:
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
            "/api/v1/projects",
            "/api/v1/me/saved-prompts",
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
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=2000)
    # An id from /api/models. Left out, the server default (LLM_PROVIDER)
    # is used; anything else is a 422.
    model: Literal["ollama", "gemini"] | None = None


@app.post("/api/query", response_model=None)
def query(
    request: QueryRequest,
    session: UserSession = Depends(require_database_access),
    configured: Settings = Depends(get_settings),
) -> dict[str, Any] | JSONResponse:
    """Answer a question with SQL, rows and the SQL that produced them.

    A plain def (not async): FastAPI runs it in a worker thread, so a
    slow model call does not hold up other requests. Rejected or failed
    queries return 200 with status "error" so the UI can show the SQL and
    a safe diagnostic; an unreachable model or database returns 503.
    Logs contain failure categories, never raw provider/database exceptions.
    """
    provider = request.model or configured.llm_provider
    if provider == "gemini" and not configured.gemini_api_key:
        body = outage_response(
            "model_not_configured", "Gemini is not set up on this server."
        )
        body["error"]["retryable"] = False  # asking again will not help
        return JSONResponse(status_code=400, content=body)
    settings = replace(configured, llm_provider=provider)
    try:
        # Authorization, retrieval, execution and cache identity use the same
        # server settings even if an operator replaces app state during runtime.
        retriever = RETRIEVER if configured == SETTINGS else _retriever(settings)
        schema = get_schema(settings)
        scope = request_scope(
            session.user["id"],
            settings,
            schema.to_prompt(),
            grant_version=session.grant_version,
            auth_epoch=session.auth_epoch,
        )
        key = scoped_cache_key(
            request.question,
            scope,
            provider,
            _model_name(provider, settings),
            retriever is not None,
            settings.answer_size_rules,
            settings.llm_fallback,
            settings.gemini_fallback_models,
            settings.ollama_model,
            settings.ollama_think,
            settings.gemini_embed_model,
        )
        answer = ANSWER_CACHE.get(key)
        if answer is None:
            answer = answer_question(
                request.question, settings, schema, retriever=retriever
            )
            ANSWER_CACHE.put(key, answer)
        else:
            log.info("answer cache hit (%s)", provider)
    except LLMError:
        log.warning(
            "query_service_failure category=model_unavailable provider=%s", provider
        )
        return JSONResponse(
            status_code=503,
            content=outage_response(
                "model_unavailable", "The language model is not reachable right now."
            ),
        )
    except DatabaseError:
        log.warning("query_service_failure category=database_unavailable")
        return JSONResponse(
            status_code=503,
            content=outage_response(
                "database_unavailable", "The database is not reachable right now."
            ),
        )
    except ContextDenied:
        log.warning("query_context_denied")
        return JSONResponse(
            status_code=503,
            content=outage_response(
                "database_unavailable", "The authorized dataset context is unavailable."
            ),
        )
    return to_response(answer, display_for(schema))


def workspace_query(
    question: str, model: str, session: UserSession, configured: Settings
) -> dict[str, Any] | JSONResponse:
    """The durable wrapper shares the legacy query safety/cache implementation."""
    return query(QueryRequest(question=question, model=model), session, configured)


app.state.workspace_query = workspace_query
