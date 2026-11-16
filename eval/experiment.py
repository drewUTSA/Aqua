"""Hash-only experiment identities and create-only evaluation artifacts.

These receipts bind bytes and declared settings, not authority or runtime index
contents. An operator-supplied index revision is recorded as a declaration.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def identity(value: Any) -> str:
    return digest(canonical(value).encode("utf-8"))


def revision(value: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("revision_invalid")
    return value


def source_identity(root: Path) -> str:
    """Bind named evaluator/runtime sources without reading configuration."""
    paths = []
    for folder in (root / "backend/nl2sql", root / "eval"):
        paths.extend(folder.rglob("*.py"))
    paths.extend(
        root / name
        for name in (
            "backend/requirements.txt",
            "tools/checks/requirements-runtime.lock",
            "db/04_retrieval.sql",
        )
    )
    records = []
    size = 0
    for path in sorted(set(paths)):
        relative = path.relative_to(root)
        if any(
            part.startswith(".") or part == "__pycache__" for part in relative.parts
        ):
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError("source_identity_unavailable")
        with path.open("rb") as source:
            raw = source.read(2 * 1024 * 1024 + 1)
        size += len(raw)
        if len(raw) > 2 * 1024 * 1024 or size > 16 * 1024 * 1024:
            raise ValueError("source_identity_budget")
        records.append((relative.as_posix(), digest(raw)))
    if not records or len(records) > 2000:
        raise ValueError("source_identity_budget")
    return identity(records)


@dataclass(frozen=True)
class Experiment:
    """Immutable canonical bytes; callers receive fresh decoded metadata."""

    payload: str

    @property
    def sha256(self) -> str:
        return digest(self.payload.encode("utf-8"))

    def metadata(self) -> dict:
        return json.loads(self.payload)


def experiment(
    dataset: bytes,
    items: list[dict],
    settings,
    schema,
    *,
    source_sha256: str,
    retrieval: bool,
    index_revision: str | None = None,
    data_revision: str | None = None,
) -> Experiment:
    """Only allowlisted, hashed semantic settings enter shareable metadata.

    Connection URLs, keys, identity secrets, raw model names, table names,
    questions, SQL and sampled schema values never appear in this receipt.
    """
    config = {
        "provider": settings.llm_provider,
        "ollama_model": settings.ollama_model,
        "ollama_think": settings.ollama_think,
        "gemini_model": settings.gemini_model,
        "gemini_fallback_models": settings.gemini_fallback_models,
        "gemini_embed_model": settings.gemini_embed_model,
        "fallback": settings.llm_fallback,
        "retrieval": retrieval,
        "hybrid": settings.retrieval_hybrid_enabled if retrieval else False,
        "answer_size_rules": settings.answer_size_rules,
        "fallback_endpoint_sha256": (
            identity(settings.ollama_base_url)
            if settings.llm_fallback and settings.llm_provider == "gemini"
            else None
        ),
    }
    selected_model = (
        settings.gemini_model
        if settings.llm_provider == "gemini"
        else settings.ollama_model
    )
    data = {
        "schema_version": 1,
        "kind": "evaluation_experiment",
        "dataset_sha256": digest(dataset),
        "selected_cases_sha256": identity(items),
        "case_count": len(items),
        "source_sha256": revision(source_sha256),
        "schema_sha256": digest(schema.to_prompt().encode("utf-8")),
        "allowlist_sha256": identity(sorted(schema.allowed_tables)),
        "config_sha256": identity(config),
        "paired_config_sha256": identity(
            {key: value for key, value in config.items() if key != "hybrid"}
        ),
        "model_sha256": identity((settings.llm_provider, selected_model)),
        "model_revision_attested": False,
        "endpoint_sha256": identity(
            (
                settings.llm_provider,
                (
                    settings.ollama_base_url
                    if settings.llm_provider == "ollama"
                    else "google-genai-default"
                ),
            )
        ),
        "embedding_sha256": (
            identity((settings.gemini_embed_model, 768)) if retrieval else None
        ),
        "retrieval": retrieval,
        "hybrid": config["hybrid"],
        "index_revision": revision(index_revision) if index_revision else None,
        "index_revision_attested": False,
        "data_revision": revision(data_revision) if data_revision else None,
        "data_revision_attested": False,
        "deadline_seconds": 120,
        "provider_call_limit": 4,
        "production_activation_authorized": False,
    }
    return Experiment(canonical(data))


def create_text(path: Path):
    """Create one artifact exclusively; do not replace an existing file/link."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(descriptor, "w", encoding="utf-8", newline="\n")


def write_json(path: Path, value: dict) -> None:
    with create_text(path) as handle:
        handle.write(canonical(value) + "\n")
