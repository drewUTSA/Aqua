"""Synthetic offline bindings only; no real bank, customer, connector or model."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from eval.banking import ReportArtifact, SourceAuthority, trusted_scope  # noqa: E402
from eval.banking.data import digest, encode  # noqa: E402

TENANT = "10000000-0000-4000-8000-000000000001"
OTHER_TENANT = "20000000-0000-4000-8000-000000000002"
PRINCIPAL = "30000000-0000-4000-8000-000000000003"
OTHER_PRINCIPAL = "40000000-0000-4000-8000-000000000004"
NOW = 1000
REPORT = "reconciliation_summary"


def scope(**changes):
    values = {
        "tenant_id": TENANT,
        "principal_id": PRINCIPAL,
        "authorization_revision": "a" * 64,
        "object_ids": frozenset({"education_object", "policy_object", "report_object"}),
        "tool_ids": frozenset(
            {"public_education", "bank_policy", "read_report", "prepare_proposal"}
        ),
        "report_ids": frozenset({REPORT}),
    }
    return trusted_scope(**(values | changes))


def artifact(**changes):
    values = {
        "artifact_id": "synthetic_report",
        "object_id": "report_object",
        "tenant_id": TENANT,
        "report_id": REPORT,
        "source_revision": "b" * 64,
        "source_version": "2026-11-16",
        "observed_at": 990,
        "expires_at": 1100,
    }
    return ReportArtifact(**(values | changes))


def source(raw, *, kind="bank_policy", **changes):
    policy = kind == "bank_policy"
    values = {
        "source_id": "synthetic_policy" if policy else "synthetic_education",
        "object_id": "policy_object" if policy else "education_object",
        "tenant_id": TENANT if policy else None,
        "department_id": "finance_accounting",
        "kind": kind,
        "publisher_id": "synthetic_issuer",
        "document_version": "2026-11-16",
        "section": "Synthetic section one",
        "content_sha256": digest(raw),
        "reviewed_sha256": digest(raw),
        "effective_at": 900,
        "checked_at": 990,
        "expires_at": 1100,
        "lifecycle": "active",
        "jurisdiction": "US",
        "classification": "internal" if policy else "public",
    }
    return SourceAuthority(**(values | changes))


def report_request(**changes):
    return encode(
        {"schemaVersion": 1, "report_id": REPORT, "artifact_id": "synthetic_report"}
        | changes
    )


def proposal_request(**changes):
    return encode(
        {
            "schemaVersion": 1,
            "action_id": "request_internal_review",
            "report_id": REPORT,
            "artifact_id": "synthetic_report",
            "object_id": "report_object",
            "note": "Review this fabricated reconciliation exception; no real records are included.",
        }
        | changes
    )
