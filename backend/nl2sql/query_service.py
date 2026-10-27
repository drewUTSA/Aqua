"""The same validation/read-only/error service runs behind both HTTP contracts."""

from dataclasses import replace
from collections.abc import Callable
from nl2sql.cache import AnswerCache, scoped_cache_key
from nl2sql.cache_scope import request_scope
from nl2sql.config import Settings
from nl2sql.control import CURRENT, ExecutionStopped, stage
from nl2sql.db import DatabaseError
from nl2sql.display import display_for
from nl2sql.errors import ContextDenied
from nl2sql.llm import LLMError
from nl2sql.pipeline import Retriever, answer_question
from nl2sql.response import outage_response, to_response
from nl2sql.schema import get_schema
from nl2sql.result_metadata import metadata_for, ResultMetadataError
from nl2sql.presentation import presentation_for


def retriever(settings: Settings) -> Retriever | None:
    if not settings.retrieval:
        return None
    from nl2sql.retrieval.select import VectorRetriever

    return VectorRetriever(settings)


def run(
    question: str,
    model: str | None,
    configured: Settings,
    principal: str,
    grant_version: int,
    auth_epoch: int,
    *,
    include_metadata: bool = False,
    cache: AnswerCache | None = None,
    schema_reader: Callable = get_schema,
    answerer: Callable = answer_question,
    retriever_factory: Callable = retriever,
) -> tuple[dict, int]:
    provider = model or configured.llm_provider
    if provider == "gemini" and not configured.gemini_api_key:
        response = outage_response(
            "model_not_configured", "Gemini is not set up on this server."
        )
        response["error"]["retryable"] = False
        return response, 400
    settings = replace(configured, llm_provider=provider)
    try:
        stage("schema")
        schema = schema_reader(settings)
        scope = request_scope(
            principal,
            settings,
            schema.to_prompt(),
            grant_version=grant_version,
            auth_epoch=auth_epoch,
        )
        budget = CURRENT.get()
        if budget:
            scope = replace(scope, context_revision=budget.context_digest)
        selected = retriever_factory(settings)
        key = scoped_cache_key(
            question,
            scope,
            provider,
            settings.gemini_model,
            selected is not None,
            settings.answer_size_rules,
            settings.llm_fallback,
            settings.gemini_fallback_models,
            settings.ollama_model,
            settings.ollama_think,
            settings.gemini_embed_model,
        )
        answer = cache.get(key) if cache else None
        if answer is None:
            answer = answerer(question, settings, schema, retriever=selected)
            if cache:
                cache.put(key, answer)
        stage("summarizing")
        metadata = (
            metadata_for(answer, source_id=scope.dataset)
            if include_metadata and answer.error is None
            else None
        )
        response = to_response(answer, display_for(schema))
        if metadata is not None:
            response["result_metadata"] = metadata
            response["presentation"] = presentation_for(
                answer,
                response,
                metadata,
                context=budget.context if budget else (),
                schema=schema,
            )
    except LLMError:
        return (
            outage_response(
                "model_unavailable", "The language model is not reachable right now."
            ),
            503,
        )
    except (DatabaseError, ContextDenied):
        return (
            outage_response(
                "database_unavailable",
                "The authorized dataset is not reachable right now.",
            ),
            503,
        )
    except ExecutionStopped:
        return (
            outage_response(
                "analysis_expired", "The analysis reached its execution budget."
            ),
            503,
        )
    except ResultMetadataError:
        return (
            outage_response(
                "result_invalid", "The result could not be represented safely."
            ),
            503,
        )
    # No raw thinking crosses this normalized response or the child IPC boundary.
    import json

    if len(json.dumps(response, ensure_ascii=False, allow_nan=False).encode()) > 240000:
        return (
            outage_response(
                "result_too_large", "The result is too large. Ask for a smaller result."
            ),
            503,
        )
    return response, 200
