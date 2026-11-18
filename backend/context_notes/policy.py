"""Finite, default-off note storage policy; no analytical/provider settings."""

from collections.abc import Mapping
from dataclasses import dataclass
import os

MAX_ACTIVE = 20
MAX_OWNER_ROWS = 200
MAX_GLOBAL_ROWS = 5000
MAX_REVISION = 9007199254740991
MAX_LABEL_CHARACTERS = 120
MAX_LABEL_BYTES = 512
MAX_BODY_UNITS = 2000
MAX_BODY_BYTES = 2048
MAX_RESPONSE_BYTES = 32768
SERVICE_SECONDS = 2
KINDS = frozenset({"note", "metric_definition"})
LIMITS = {
    "active_notes": MAX_ACTIVE,
    "label_characters": MAX_LABEL_CHARACTERS,
    "label_bytes": MAX_LABEL_BYTES,
    "body_utf16_units": MAX_BODY_UNITS,
    "body_bytes": MAX_BODY_BYTES,
    "draft_utf16_units": 2000,
    "draft_bytes": 8000,
}


@dataclass(frozen=True)
class ContextNotesPolicy:
    enabled: bool = False

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ValueError("context_notes_policy_invalid")


def load_policy(environ: Mapping[str, str] | None = None) -> ContextNotesPolicy:
    """An invalid host flag fails startup rather than guessing activation."""
    value = (os.environ if environ is None else environ).get(
        "CONTEXT_NOTES_ENABLED", "false"
    )
    if value not in {"true", "false"}:
        raise ValueError("context_notes_policy_invalid")
    return ContextNotesPolicy(value == "true")
