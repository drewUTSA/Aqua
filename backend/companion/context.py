"""Project bounded reviewed data independently from caller authorization."""

from companion.data_contract import (
    BINDING,
    MAX_AGE_SECONDS,
    MAX_BLOCKS,
    MAX_CONTEXT_BYTES,
    CompanionDenied,
    Context,
    _binding,
    _encode,
    _identifier,
    _load,
    _payload,
)


def assemble_context(raw, *, actor_id, scope_id, dataset, schema_revision, now):
    """Project explicitly reviewed data, never system instructions or auth proof."""
    binding = _binding(actor_id, scope_id, dataset, schema_revision, now)
    return project(raw, binding=binding, now=now)


def project(raw: bytes, *, binding: tuple, now: int) -> Context:
    """Share projection with the explicitly separate application-only domain."""
    pack = _load(raw)
    if (
        type(pack) is not dict
        or set(pack) != BINDING | {"schemaVersion", "blocks"}
        or type(pack["schemaVersion"]) is not int
        or pack["schemaVersion"] != 1
    ):
        raise CompanionDenied("context_schema_invalid")
    expected = dict(
        zip(("actor_id", "scope_id", "dataset", "schema_revision"), binding)
    )
    if any(pack[k] != v for k, v in expected.items()):
        raise CompanionDenied("context_binding_invalid")
    blocks = pack["blocks"]
    if type(blocks) is not list or not 1 <= len(blocks) <= MAX_BLOCKS:
        raise CompanionDenied("block_budget_invalid")
    projected, artifacts, expiry = [], {}, now + MAX_AGE_SECONDS
    for block in blocks:
        if type(block) is not dict or set(block) != BINDING | {
            "id",
            "kind",
            "approved",
            "observed_at",
            "expires_at",
            "data",
        }:
            raise CompanionDenied("block_schema_invalid")
        if block["approved"] is not True or any(
            block[k] != v for k, v in expected.items()
        ):
            raise CompanionDenied("block_binding_invalid")
        key, kind = block["id"], block["kind"]
        if not _identifier(key) or key in artifacts or type(kind) is not str:
            raise CompanionDenied("artifact_invalid")
        observed, expires = block["observed_at"], block["expires_at"]
        if (
            type(observed) is not int
            or type(expires) is not int
            or not 0 <= observed <= now < expires <= observed + MAX_AGE_SECONDS
        ):
            raise CompanionDenied("context_stale")
        _payload(kind, block["data"])
        projected.append({"id": key, "kind": kind, "data": block["data"]})
        artifacts[key], expiry = kind, min(expiry, expires)
    data = _encode(
        {
            "schemaVersion": 1,
            "content_role": "untrusted_data",
            "dataset": binding[2],
            "schema_revision": binding[3],
            "blocks": projected,
        }
    )
    if len(data) > MAX_CONTEXT_BYTES:
        raise CompanionDenied("context_budget_invalid")
    return Context(data, binding, tuple(artifacts.items()), now, expiry)
