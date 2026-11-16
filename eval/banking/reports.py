"""Validate closed report/artifact references; never run SQL or fetch a URL."""

from dataclasses import dataclass

from eval.banking.catalog import REPORT_IDS
from eval.banking.data import (
    clock,
    encode,
    fields,
    identifier,
    load,
    require,
    revision,
    uuid,
    version,
)
from eval.banking.scope import scope_fingerprint, validate_scope

MAX_REPORT_LEASE = 300


@dataclass(frozen=True)
class ReportArtifact:
    artifact_id: str
    object_id: str
    tenant_id: str
    report_id: str
    source_revision: str
    source_version: str
    observed_at: int
    expires_at: int


def validate_artifact(artifact, scope, now):
    validate_scope(scope)
    require(type(artifact) is ReportArtifact and clock(now), "report_artifact_required")
    require(
        uuid(artifact.tenant_id) and artifact.tenant_id == scope.tenant_id,
        "report_tenant",
    )
    require(
        type(artifact.report_id) is str
        and artifact.report_id in REPORT_IDS
        and artifact.report_id in scope.report_ids
        and "read_report" in scope.tool_ids,
        "report_scope_denied",
    )
    require(
        all(identifier(value) for value in (artifact.object_id, artifact.artifact_id))
        and version(artifact.source_version)
        and artifact.object_id in scope.object_ids,
        "report_object_scope",
    )
    require(revision(artifact.source_revision), "report_source_revision")
    require(
        clock(artifact.observed_at)
        and clock(artifact.expires_at)
        and artifact.observed_at <= now < artifact.expires_at
        and 0 < artifact.expires_at - artifact.observed_at <= MAX_REPORT_LEASE,
        "report_stale",
    )


def reference(raw, *, scope, artifact, now):
    validate_artifact(artifact, scope, now)
    value = load(raw)
    fields(value, {"schemaVersion", "report_id", "artifact_id"})
    require(
        type(value["schemaVersion"]) is int and value["schemaVersion"] == 1,
        "report_version",
    )
    require(
        value["report_id"] == artifact.report_id
        and value["artifact_id"] == artifact.artifact_id,
        "report_reference_changed",
    )
    return value


def select_report(raw, *, scope, artifact, now):
    """A validated reference is advisory; no result or query is produced."""
    value = reference(raw, scope=scope, artifact=artifact, now=now)
    return encode(
        {
            **value,
            "domain": "banking_report_reference_v1",
            "read_only": True,
            "execution_enabled": False,
            "scope_sha256": scope_fingerprint(scope),
            "object_id": artifact.object_id,
            "source_revision": artifact.source_revision,
            "source_version": artifact.source_version,
            "observed_at": artifact.observed_at,
            "expires_at": artifact.expires_at,
        }
    )
