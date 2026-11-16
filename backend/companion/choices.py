"""Validate a closed choice; this module never executes it."""

from companion.data_contract import (
    TOOLS,
    CompanionDenied,
    Context,
    _binding,
    _encode,
    _load,
)


def validate_choices(
    raw,
    *,
    context,
    actor_id,
    scope_id,
    dataset,
    schema_revision,
    now,
    available_capabilities=frozenset(),
    authorized_artifact_ids=frozenset(),
):
    """Validate closed offline choices only. No executor or live availability claim."""
    binding = _binding(actor_id, scope_id, dataset, schema_revision, now)
    return check(
        raw,
        context=context,
        binding=binding,
        now=now,
        available_capabilities=available_capabilities,
        authorized_artifact_ids=authorized_artifact_ids,
    )


def check(
    raw: bytes,
    *,
    context: Context,
    binding: tuple,
    now: int,
    available_capabilities: frozenset,
    authorized_artifact_ids: frozenset,
) -> bytes:
    """Common structural check; callers must independently establish authority."""
    if (
        type(context) is not Context
        or context.binding != binding
        or not context.created_at <= now < context.expires_at
    ):
        raise CompanionDenied("context_binding_invalid")
    artifacts = dict(context.artifacts)
    if (
        type(available_capabilities) is not frozenset
        or not available_capabilities <= TOOLS.keys()
        or type(authorized_artifact_ids) is not frozenset
        or not authorized_artifact_ids <= artifacts.keys()
    ):
        raise CompanionDenied("availability_invalid")
    request = _load(raw)
    if (
        type(request) is not dict
        or set(request) != {"schemaVersion", "choices"}
        or type(request["schemaVersion"]) is not int
        or request["schemaVersion"] != 1
    ):
        raise CompanionDenied("choice_schema_invalid")
    choices = request["choices"]
    if type(choices) is not list or len(choices) > 3:
        raise CompanionDenied("choice_budget_invalid")
    seen = set()
    for choice in choices:
        if type(choice) is not dict or set(choice) != {"capability_id", "artifact_id"}:
            raise CompanionDenied("choice_schema_invalid")
        capability, artifact = choice["capability_id"], choice["artifact_id"]
        if (
            type(capability) is not str
            or type(artifact) is not str
            or capability not in available_capabilities
            or artifact not in authorized_artifact_ids
            or artifacts[artifact] != TOOLS[capability]
            or capability in seen
        ):
            raise CompanionDenied("choice_denied")
        seen.add(capability)
    return _encode({"schemaVersion": 1, "choices": choices, "execution_enabled": False})
