"""Application-only feature policy never crosses the analytical worker boundary."""

from dataclasses import dataclass
import os
from collections.abc import Mapping


@dataclass(frozen=True)
class CompanionPolicy:
    enabled: bool = False

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ValueError("companion_policy_invalid")


def load_policy(environ: Mapping[str, str] | None = None) -> CompanionPolicy:
    """An invalid flag fails startup rather than enabling a guessed policy."""
    value = (os.environ if environ is None else environ).get(
        "COMPANION_ENABLED", "false"
    )
    if value not in {"true", "false"}:
        raise ValueError("companion_policy_invalid")
    return CompanionPolicy(enabled=value == "true")
