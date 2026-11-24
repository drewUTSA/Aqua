"""Host-selected fictional scope is separate from app identity and data grants."""

from collections.abc import Mapping
from dataclasses import dataclass, field
import os
from uuid import UUID

PERSONAS = frozenset({"none", "teller", "analyst", "manager"})


@dataclass(frozen=True)
class BankDemoPolicy:
    enabled: bool = False
    persona: str = "none"
    account_personas: tuple[tuple[str, str], ...] | None = field(
        default=None, repr=False
    )

    def __post_init__(self):
        if (
            type(self.enabled) is not bool
            or type(self.persona) is not str
            or self.persona not in PERSONAS
        ):
            raise ValueError("bank_demo_policy_invalid")
        if self.account_personas is None:
            return
        if (
            self.persona != "none"
            or type(self.account_personas) is not tuple
            or len(self.account_personas) > 64
        ):
            raise ValueError("bank_demo_policy_invalid")
        seen = set()
        for entry in self.account_personas:
            if type(entry) is not tuple or len(entry) != 2:
                raise ValueError("bank_demo_policy_invalid")
            owner, role = entry
            if type(owner) is not str or type(role) is not str or role not in PERSONAS:
                raise ValueError("bank_demo_policy_invalid")
            try:
                canonical = str(UUID(owner))
            except ValueError:
                raise ValueError("bank_demo_policy_invalid") from None
            if owner != canonical or owner in seen:
                raise ValueError("bank_demo_policy_invalid")
            seen.add(owner)

    def for_account(self, owner: str) -> str:
        if self.account_personas is None:
            return self.persona
        return next(
            (role for account, role in self.account_personas if account == owner),
            "none",
        )


def load_policy(environ: Mapping[str, str] | None = None) -> BankDemoPolicy:
    values = os.environ if environ is None else environ
    enabled = values.get("BANK_DEMO_ENABLED", "false")
    if enabled not in {"true", "false"}:
        raise ValueError("bank_demo_policy_invalid")
    raw = values.get("BANK_DEMO_ACCOUNT_PERSONAS")
    assignments = None
    if raw is not None:
        if type(raw) is not str or len(raw) > 4096:
            raise ValueError("bank_demo_policy_invalid")
        assignments = (
            tuple(tuple(item.strip().split("=")) for item in raw.split(","))
            if raw.strip()
            else ()
        )
    return BankDemoPolicy(
        enabled == "true", values.get("BANK_DEMO_PERSONA", "none"), assignments
    )
