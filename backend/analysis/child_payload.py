"""Only analytical configuration crosses the child pipe; app/identity secrets do not."""

from dataclasses import asdict
import os
from nl2sql.config import Settings

FIELDS = frozenset(
    {
        "ollama_base_url",
        "ollama_model",
        "ollama_think",
        "database_url",
        "gemini_api_key",
        "gemini_model",
        "gemini_fallback_models",
        "gemini_embed_model",
        "llm_provider",
        "llm_fallback",
        "retrieval",
        "answer_size_rules",
        "answer_cache_seconds",
    }
)


def payload(job: dict, question: str, settings: Settings, remaining: float) -> dict:
    return {
        "question": question,
        "model": job["model"],
        "settings": {k: v for k, v in asdict(settings).items() if k in FIELDS},
        "principal": str(job["user_id"]),
        "grant_version": job["grant_version"],
        "auth_epoch": job["auth_epoch"],
        "context": job["context"],
        "context_digest": bytes(job["context_digest"]).hex(),
        "remaining_seconds": max(0.01, min(120.0, remaining)),
        "parent_pid": os.getpid(),
        "workspace": job["request_id"] is not None,
    }
