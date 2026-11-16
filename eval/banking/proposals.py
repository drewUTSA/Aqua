"""Ephemeral exact-payload proposals. No approval, persistence or execution."""

from dataclasses import dataclass

from eval.banking.catalog import ACTION_IDS
from eval.banking.data import (
    MAX_BYTES,
    clock,
    digest,
    encode,
    fields,
    load,
    require,
    revision,
    text,
)
from eval.banking.reports import reference, validate_artifact
from eval.banking.scope import scope_fingerprint

MAX_PROPOSAL_LEASE = 300
PAYLOAD_FIELDS = {
    "schemaVersion",
    "action_id",
    "report_id",
    "artifact_id",
    "object_id",
    "note",
}
ENVELOPE_FIELDS = {
    "schemaVersion",
    "domain",
    "status",
    "tenant_id",
    "principal_id",
    "scope_sha256",
    "source_revision",
    "source_version",
    "created_at",
    "expires_at",
    "payload",
    "requires_human_approval",
    "approval_recorded",
    "execution_enabled",
}


@dataclass(frozen=True)
class Proposal:
    data: bytes
    sha256: str


def payload(raw, *, scope, artifact, now):
    validate_artifact(artifact, scope, now)
    require("prepare_proposal" in scope.tool_ids, "proposal_scope_denied")
    value = load(raw)
    fields(value, PAYLOAD_FIELDS)
    require(
        type(value["action_id"]) is str
        and value["action_id"] in ACTION_IDS
        and value["object_id"] == artifact.object_id
        and text(value["note"], 1024, multiline=True),
        "proposal_payload",
    )
    reference(
        encode(
            {key: value[key] for key in ("schemaVersion", "report_id", "artifact_id")}
        ),
        scope=scope,
        artifact=artifact,
        now=now,
    )
    return value


def create_proposal(raw, *, scope, artifact, now, expires_at):
    """Prepare for human review; a digest is neither a signature nor approval."""
    value = payload(raw, scope=scope, artifact=artifact, now=now)
    require(
        clock(expires_at)
        and now < expires_at <= artifact.expires_at
        and expires_at - now <= MAX_PROPOSAL_LEASE,
        "proposal_expiry",
    )
    data = encode(
        {
            "schemaVersion": 1,
            "domain": "banking_proposal_v1",
            "status": "proposal_only",
            "tenant_id": scope.tenant_id,
            "principal_id": scope.principal_id,
            "scope_sha256": scope_fingerprint(scope),
            "source_revision": artifact.source_revision,
            "source_version": artifact.source_version,
            "created_at": now,
            "expires_at": expires_at,
            "payload": value,
            "requires_human_approval": True,
            "approval_recorded": False,
            "execution_enabled": False,
        }
    )
    return Proposal(data, digest(data))


def recheck_proposal(proposal, raw, *, scope, artifact, now):
    """Recheck an unchanged draft with fresh caller inputs, still without approval."""
    require(
        type(proposal) is Proposal
        and type(proposal.data) is bytes
        and 0 < len(proposal.data) <= MAX_BYTES
        and revision(proposal.sha256)
        and digest(proposal.data) == proposal.sha256,
        "proposal_bytes_changed",
    )
    envelope = load(proposal.data)
    fields(envelope, ENVELOPE_FIELDS)
    require(
        clock(now)
        and clock(envelope["created_at"])
        and clock(envelope["expires_at"])
        and envelope["created_at"] <= now < envelope["expires_at"],
        "proposal_expired",
    )
    value = payload(raw, scope=scope, artifact=artifact, now=now)
    require(encode(envelope["payload"]) == encode(value), "proposal_payload_changed")
    require(
        envelope["tenant_id"] == scope.tenant_id
        and envelope["principal_id"] == scope.principal_id
        and envelope["scope_sha256"] == scope_fingerprint(scope),
        "proposal_principal_changed",
    )
    require(
        envelope["source_revision"] == artifact.source_revision
        and envelope["source_version"] == artifact.source_version,
        "proposal_source_changed",
    )
    require(
        type(envelope["schemaVersion"]) is int
        and envelope["schemaVersion"] == 1
        and envelope["domain"] == "banking_proposal_v1"
        and envelope["status"] == "proposal_only"
        and envelope["requires_human_approval"] is True
        and envelope["approval_recorded"] is False
        and envelope["execution_enabled"] is False,
        "proposal_cannot_approve",
    )
    require(
        0 < envelope["expires_at"] - envelope["created_at"] <= MAX_PROPOSAL_LEASE
        and envelope["expires_at"] <= artifact.expires_at
        and proposal.data == encode(envelope),
        "proposal_envelope_changed",
    )
    return encode(
        {
            "schemaVersion": 1,
            "status": "proposal_only",
            "proposal_sha256": proposal.sha256,
            "requires_human_approval": True,
            "approval_recorded": False,
            "execution_enabled": False,
        }
    )
