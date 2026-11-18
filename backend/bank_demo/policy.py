"""Host-selected fictional scope is separate from app identity and data grants."""

from collections.abc import Mapping
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class BankDemoPolicy:
    enabled: bool = False
    persona: str = "none"

    def __post_init__(self):
        if (
            type(self.enabled) is not bool
            or type(self.persona) is not str
            or self.persona not in {"none", "teller", "analyst", "manager"}
        ):
            raise ValueError("bank_demo_policy_invalid")


def load_policy(environ: Mapping[str, str] | None = None) -> BankDemoPolicy:
    values = os.environ if environ is None else environ
    enabled = values.get("BANK_DEMO_ENABLED", "false")
    if enabled not in {"true", "false"}:
        raise ValueError("bank_demo_policy_invalid")
    return BankDemoPolicy(enabled == "true", values.get("BANK_DEMO_PERSONA", "none"))
