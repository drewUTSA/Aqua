"""Caller-owned bank bindings. This is not an IdP or an authorization service."""

from dataclasses import dataclass

from eval.banking.catalog import REPORT_IDS, TOOL_IDS
from eval.banking.data import digest, encode, identifier, require, revision, uuid


@dataclass(frozen=True)
class BankScope:
    tenant_id: str
    principal_id: str
    authorization_revision: str
    object_ids: frozenset[str]
    tool_ids: frozenset[str]
    report_ids: frozenset[str]


def validate_scope(scope):
    require(type(scope) is BankScope, "caller_scope_required")
    require(
        uuid(scope.tenant_id) and uuid(scope.principal_id), "bank_principal_binding"
    )
    require(revision(scope.authorization_revision), "authorization_revision")
    require(
        type(scope.object_ids) is frozenset
        and len(scope.object_ids) <= 64
        and all(identifier(value) for value in scope.object_ids),
        "object_scope",
    )
    require(
        type(scope.tool_ids) is frozenset and scope.tool_ids <= TOOL_IDS, "tool_scope"
    )
    require(
        type(scope.report_ids) is frozenset and scope.report_ids <= REPORT_IDS,
        "report_scope",
    )
    return scope


def trusted_scope(
    *,
    tenant_id,
    principal_id,
    authorization_revision,
    object_ids=frozenset(),
    tool_ids=frozenset(),
    report_ids=frozenset(),
):
    """Only a future authenticated bank adapter may supply these arguments.

    An email, department, prompt role, matching hash or this dataclass cannot
    establish bank identity, object access, an approval or a current grant.
    """
    return validate_scope(
        BankScope(
            tenant_id,
            principal_id,
            authorization_revision,
            object_ids,
            tool_ids,
            report_ids,
        )
    )


def scope_fingerprint(scope):
    validate_scope(scope)
    return digest(
        encode(
            {
                "domain": "bank_tenant_scope_v1",
                "tenant_id": scope.tenant_id,
                "principal_id": scope.principal_id,
                "authorization_revision": scope.authorization_revision,
                "object_ids": sorted(scope.object_ids),
                "tool_ids": sorted(scope.tool_ids),
                "report_ids": sorted(scope.report_ids),
            }
        )
    )
