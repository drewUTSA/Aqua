"""Bounded Ollama transport; the shared wrapper owns provider policy."""

from typing import Any
import httpx
from nl2sql.config import Settings
from nl2sql.control import CURRENT, remaining
from nl2sql.llm import (
    Completion,
    LLMError,
    THINKING_OPTIONS,
    NON_THINKING_OPTIONS,
    SEED,
    NUM_CTX,
    TIMEOUT,
)


def complete(
    prompt: str,
    settings: Settings,
    system: str | None,
    json_schema: dict[str, Any] | None,
    client: httpx.Client | None,
) -> Completion:
    messages = [{"role": "user", "content": prompt}]
    if system:
        messages.insert(0, {"role": "system", "content": system})

    options = THINKING_OPTIONS if settings.ollama_think else NON_THINKING_OPTIONS
    body: dict[str, Any] = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": False,
        "think": settings.ollama_think,
        "options": {**options, "seed": SEED, "num_ctx": NUM_CTX},
    }
    if json_schema is not None:
        body["format"] = json_schema
    if CURRENT.get():
        body["options"]["num_predict"] = 4096

    url = f"{settings.ollama_base_url}/api/chat"
    owns_client = client is None
    if owns_client:
        timeout = (
            httpx.Timeout(remaining(45), connect=remaining(5))
            if CURRENT.get()
            else TIMEOUT
        )
        client = httpx.Client(timeout=timeout)
    try:
        if CURRENT.get():
            # Bound response bytes while reading, before JSON parsing.
            import json

            with client.stream("POST", url, json=body) as response:
                response.raise_for_status()
                raw = bytearray()
                for chunk in response.iter_bytes():
                    remaining(45)
                    if len(raw) + len(chunk) > 1048576:
                        raise LLMError("Ollama response exceeds its budget.")
                    raw.extend(chunk)
                data = json.loads(raw)
        else:
            response = client.post(url, json=body)
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException as exc:
        raise LLMError("Ollama took too long to respond.") from exc
    except httpx.HTTPStatusError as exc:
        # Ollama explains errors in the body, e.g. a model that isn't pulled.
        raise LLMError(f"Ollama returned HTTP {exc.response.status_code}.") from None
    except httpx.RequestError:
        raise LLMError("Cannot connect to Ollama.") from None
    except ValueError as exc:
        raise LLMError("Ollama returned a reply that is not JSON.") from exc
    finally:
        if owns_client:
            client.close()

    message = data.get("message") or {}
    text = (message.get("content") or "").strip()
    if CURRENT.get() and len(text.encode()) > 32768:
        raise LLMError("Generated SQL exceeds its budget.")
    if not text:
        raise LLMError("Ollama returned no answer.")
    return Completion(
        text=text,
        thinking=(message.get("thinking") or "").strip(),
        model=data.get("model", settings.ollama_model),
    )
