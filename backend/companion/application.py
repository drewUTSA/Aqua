"""Application-help domain reuses context/choice guards without a fake grant."""

import hashlib
import time
from uuid import NAMESPACE_URL, uuid5

from auth.security import UserSession
from companion.choices import check
from companion.context import project
from companion.data_contract import CompanionDenied, Context, _encode, _load
from companion.knowledge import Knowledge


def application_context(
    session: UserSession, pack: Knowledge, *, now: int | None = None
) -> Context:
    """The server supplies these bindings after fresh session authorization."""
    instant = int(time.time()) if now is None else now
    owner = session.user["id"]
    scope = str(
        uuid5(
            NAMESPACE_URL,
            "aqua-help:"
            + hashlib.sha256(
                _encode(
                    [
                        owner,
                        session.auth_epoch,
                        session.history_generation,
                        session.token_digest.hex(),
                    ]
                )
            ).hexdigest(),
        )
    )
    binding = (owner, scope, "application", pack.revision)
    fields = dict(zip(("actor_id", "scope_id", "dataset", "schema_revision"), binding))
    raw = _encode(
        {
            "schemaVersion": 1,
            **fields,
            "blocks": [
                {
                    **fields,
                    "id": record.id,
                    "kind": "aqua_help",
                    "approved": True,
                    "observed_at": instant,
                    "expires_at": instant + 60,
                    "data": {"topic": record.topic, "text": record.text},
                }
                for record in pack.records
            ],
        }
    )
    return project(raw, binding=binding, now=instant)


def help_choice(raw: bytes, *, context: Context, current: Context, now: int) -> bytes:
    """One lookup of a current approved artifact; no supplied tool is executed."""
    value = _load(raw)
    if (
        type(value) is not dict
        or type(value.get("choices")) is not list
        or len(value["choices"]) != 1
    ):
        raise CompanionDenied("choice_budget_invalid")
    if current.binding[2] != "application":
        raise CompanionDenied("context_binding_invalid")
    return check(
        raw,
        context=context,
        binding=current.binding,
        now=now,
        available_capabilities=frozenset({"app_help"}),
        authorized_artifact_ids=frozenset(key for key, _ in current.artifacts),
    )
