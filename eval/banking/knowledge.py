"""Reviewed source projection; public education never becomes a bank policy."""

from dataclasses import dataclass

from eval.banking.catalog import DEPARTMENT_IDS
from eval.banking.data import (
    MAX_BYTES,
    clock,
    digest,
    encode,
    fields,
    identifier,
    load,
    require,
    revision,
    text,
    uuid,
    version,
)
from eval.banking.scope import scope_fingerprint, validate_scope

MAX_SOURCE_LEASE = 86400


@dataclass(frozen=True)
class SourceAuthority:
    source_id: str
    object_id: str
    tenant_id: str | None
    department_id: str
    kind: str
    publisher_id: str
    document_version: str
    section: str
    content_sha256: str
    reviewed_sha256: str
    effective_at: int
    checked_at: int
    expires_at: int
    lifecycle: str
    jurisdiction: str
    classification: str


def validate_source(source, scope, now, required_kind):
    """Metadata is a trusted-registry declaration, not proof of its issuer."""
    validate_scope(scope)
    require(type(source) is SourceAuthority and clock(now), "source_authority_required")
    require(
        type(required_kind) is str
        and required_kind in {"public_education", "bank_policy"}
        and source.kind == required_kind,
        "source_kind_required",
    )
    require(
        all(
            identifier(value)
            for value in (source.source_id, source.object_id, source.publisher_id)
        )
        and version(source.document_version),
        "source_identity",
    )
    require(
        source.kind in scope.tool_ids and source.object_id in scope.object_ids,
        "source_scope_denied",
    )
    require(
        type(source.department_id) is str
        and source.department_id in DEPARTMENT_IDS
        and text(source.section, 160),
        "source_citation",
    )
    require(
        source.lifecycle == "active" and source.jurisdiction == "US",
        "source_not_current",
    )
    require(
        revision(source.content_sha256)
        and source.reviewed_sha256 == source.content_sha256,
        "source_review_binding",
    )
    require(
        all(
            clock(value)
            for value in (source.effective_at, source.checked_at, source.expires_at)
        ),
        "source_time",
    )
    require(
        source.effective_at <= now
        and source.checked_at <= now < source.expires_at
        and 0 < source.expires_at - source.checked_at <= MAX_SOURCE_LEASE,
        "source_stale",
    )
    if source.kind == "public_education":
        require(
            source.tenant_id is None and source.classification == "public",
            "public_source_boundary",
        )
    else:
        require(
            uuid(source.tenant_id)
            and source.tenant_id == scope.tenant_id
            and type(source.classification) is str
            and source.classification in {"internal", "restricted"},
            "bank_policy_tenant",
        )


def project_knowledge(raw, *, scope, source, now, required_kind):
    """Return a small cited data object, never a policy decision or model answer."""
    validate_source(source, scope, now, required_kind)
    require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, "input_budget")
    require(digest(raw) == source.content_sha256, "source_bytes_changed")
    value = load(raw)
    fields(value, {"schemaVersion", "text"})
    require(
        type(value["schemaVersion"]) is int
        and value["schemaVersion"] == 1
        and text(value["text"], 4096, multiline=True),
        "source_text",
    )
    return encode(
        {
            "schemaVersion": 1,
            "domain": "banking_knowledge_v1",
            "kind": source.kind,
            "text": value["text"],
            "data_only": True,
            "execution_enabled": False,
            "bank_policy": source.kind == "bank_policy",
            "jurisdiction": source.jurisdiction,
            "scope_sha256": scope_fingerprint(scope),
            "classification": source.classification,
            "citation": {
                "source_id": source.source_id,
                "publisher_id": source.publisher_id,
                "document_version": source.document_version,
                "section": source.section,
                "content_sha256": source.content_sha256,
            },
            "effective_at": source.effective_at,
            "checked_at": source.checked_at,
            "expires_at": source.expires_at,
        }
    )
