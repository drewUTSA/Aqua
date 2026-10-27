"""Owned Gemini client with deadline-aware retries/output and deterministic close."""

from typing import Any
import httpx
from nl2sql.config import Settings
from nl2sql.control import CURRENT, remaining
from nl2sql.llm import (
    Completion,
    LLMError,
    SEED,
    GEMINI_TIMEOUT_MS,
    GEMINI_ATTEMPTS,
    GEMINI_RETRY_DELAY_S,
    GEMINI_RETRY_MAX_DELAY_S,
    GEMINI_RETRY_CODES,
    FALLBACK_CODES,
)


def complete(
    prompt: str,
    settings: Settings,
    system: str | None,
    json_schema: dict[str, Any] | None,
    client: Any,
) -> Completion:
    """Gemini API through the google-genai SDK.

    Gemma models on the API take neither a system instruction nor a JSON
    schema, so for them the rules go at the top of the prompt and
    generate.extract_sql reads the SQL out of a code fence instead.
    Temperature is left at the API default, which Google recommends for
    current Gemini models.
    """
    if not settings.gemini_api_key:
        raise LLMError("GEMINI_API_KEY is not set, so Gemini cannot be used.")
    from google.genai import errors, types  # Ollama-only setups never load it

    model = settings.gemini_model
    # No tools are passed, so automatic function calling only adds a
    # warning to every call's log; switch it off.
    config: dict[str, Any] = {
        "seed": SEED,
        "automatic_function_calling": types.AutomaticFunctionCallingConfig(
            disable=True
        ),
    }
    if CURRENT.get():
        config["max_output_tokens"] = 4096
    contents = prompt
    if model.lower().startswith("gemma"):
        if system:
            contents = f"{system}\n\n{prompt}"
    else:
        if system:
            config["system_instruction"] = system
        if json_schema is not None:
            config["response_mime_type"] = "application/json"
            config["response_json_schema"] = json_schema

    owns_client = client is None
    if owns_client:
        from google import genai

        client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(
                timeout=(
                    max(1, int(remaining(45) * 1000))
                    if CURRENT.get()
                    else GEMINI_TIMEOUT_MS
                ),
                retry_options=types.HttpRetryOptions(
                    attempts=1 if CURRENT.get() else GEMINI_ATTEMPTS,
                    initial_delay=GEMINI_RETRY_DELAY_S,
                    max_delay=GEMINI_RETRY_MAX_DELAY_S,
                    http_status_codes=GEMINI_RETRY_CODES,
                ),
            ),
        )
    try:
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(**config),
        )
    except errors.APIError as exc:
        raise LLMError(
            f"Gemini returned HTTP {exc.code}.",
            transient=exc.code in FALLBACK_CODES,
        ) from exc
    except httpx.TimeoutException as exc:
        raise LLMError("Gemini took too long to respond.", transient=True) from exc
    except httpx.HTTPError:
        raise LLMError("Cannot reach the Gemini API.", transient=True) from None
    finally:
        if owns_client:
            client.close()

    text = (response.text or "").strip()
    if CURRENT.get() and len(text.encode()) > 32768:
        raise LLMError("Generated SQL exceeds its budget.")
    if not text:
        # Provider finish text may echo submitted/private content; use a fixed hint.
        # An empty reply (a safety or recitation stop) may not repeat on
        # another model, so let the chain move on.
        raise LLMError("Gemini returned no answer.", transient=True)
    return Completion(
        text=text,
        thinking="",
        model=getattr(response, "model_version", None) or model,
    )
