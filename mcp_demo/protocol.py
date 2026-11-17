"""Small, fixed demo scopes and bounded data; no transport or bank authority."""

import hashlib
import json
import re
from dataclasses import dataclass
from types import MappingProxyType

from eval.banking.catalog import DEPARTMENT_IDS, REPORTS, TOOL_IDS
from eval.banking.scope import BankScope, trusted_scope, validate_scope

DEMO_TENANT = "11111111-1111-4111-8111-111111111111"
MAX_FRAME_BYTES = 32768
MAX_RESULT_BYTES = 32768
MAX_PAYLOAD_BYTES = 16000
HANDLER_SECONDS = 2
PERSONAS = ("teller", "analyst", "manager")
_DEPARTMENTS = {
    "none": frozenset(),
    "teller": frozenset({"retail_deposits", "customer_service"}),
    "analyst": frozenset(
        {
            "finance_accounting",
            "treasury_alm",
            "credit_underwriting",
            "commercial_lending",
        }
    ),
    "manager": DEPARTMENT_IDS,
}
_PRINCIPALS = {
    "none": "22222222-2222-4222-8222-222222222220",
    "teller": "22222222-2222-4222-8222-222222222221",
    "analyst": "22222222-2222-4222-8222-222222222222",
    "manager": "22222222-2222-4222-8222-222222222223",
}


class DemoDenied(ValueError):
    """A fixed safe category; never a prompt or an external exception string."""


def require(condition, category="demo_request_denied"):
    if not condition:
        raise DemoDenied(category)


def canonical(value):
    try:
        return json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise DemoDenied("demo_data_invalid") from None


AUTHORIZATION_REVISION = hashlib.sha256(
    canonical({name: sorted(values) for name, values in _DEPARTMENTS.items()})
).hexdigest()


@dataclass(frozen=True)
class DemoActor:
    persona: str
    scope: BankScope


def _actor(persona):
    departments = _DEPARTMENTS[persona]
    return DemoActor(
        persona,
        trusted_scope(
            tenant_id=DEMO_TENANT,
            principal_id=_PRINCIPALS[persona],
            authorization_revision=AUTHORIZATION_REVISION,
            object_ids=departments | {"public_finance"} if departments else frozenset(),
            tool_ids=TOOL_IDS if departments else frozenset(),
            report_ids=frozenset(
                report
                for report, department in REPORTS.items()
                if department in departments
            ),
        ),
    )


_ACTORS = MappingProxyType({persona: _actor(persona) for persona in _DEPARTMENTS})


def actor_for(persona="none"):
    """Only the process launcher selects a persona; this is not bank identity."""
    require(type(persona) is str and persona in _ACTORS, "demo_persona_invalid")
    return _ACTORS[persona]


def require_actor(actor):
    require(
        type(actor) is DemoActor
        and type(actor.persona) is str
        and actor.persona in _ACTORS,
        "demo_actor_invalid",
    )
    validate_scope(actor.scope)
    require(actor == _ACTORS[actor.persona], "demo_actor_changed")
    return actor


def require_tool(actor, tool):
    require_actor(actor)
    require(tool in actor.scope.tool_ids, "demo_scope_denied")


def envelope(payload, *, source_revision, as_of):
    require(
        type(payload) is dict and len(canonical(payload)) <= MAX_PAYLOAD_BYTES,
        "demo_output_budget",
    )
    require(
        type(source_revision) is str and re.fullmatch(r"[a-f0-9]{64}", source_revision),
        "demo_source_invalid",
    )
    require(as_of == "2026-11-16", "demo_asof_invalid")
    result = {
        "schemaVersion": 1,
        "synthetic": True,
        "demo_only": True,
        "sourceRevision": source_revision,
        "asOf": as_of,
        "jurisdiction": "US",
        "currency": "USD",
        "execution_enabled": False,
        "approval_recorded": False,
        "data": payload,
    }
    require(len(canonical(result)) <= MAX_RESULT_BYTES, "demo_output_budget")
    return result
