"""Bounded literal guidance over original fictional procedures and three sources."""

from dataclasses import dataclass
import hashlib
import json
import re
import unicodedata

from eval.banking.data import encode, text
from eval.banking.knowledge import SourceAuthority, project_knowledge
from mcp_demo.data import AS_OF, AS_OF_EPOCH, DEMO_TENANT
from mcp_demo.protocol import canonical, require, require_actor


@dataclass(frozen=True)
class Entry:
    id: str
    department: str
    title: str
    keywords: tuple[str, ...]
    body: str
    kind: str = "bank_policy"
    citation: str = "aqua-demo://fictional-procedures/v1"
    version: str = "fictional-demo-v1"
    publisher: str = "aqua_demo"


ENTRIES = (
    Entry(
        "deposit_help",
        "retail_deposits",
        "Fictional deposit review",
        ("deposit", "deposits", "checking", "savings", "branch", "balance", "fees"),
        "Fictional demo procedure: open deposit_portfolio_summary to compare branch/product balances. Posted deposits increase and posted withdrawals reduce the November opening buckets; exceptions are excluded. This fixture has no customer accounts or approved fee schedule. For a fee quote, ask for the bank's effective authorized schedule.",
    ),
    Entry(
        "service_help",
        "customer_service",
        "Fictional service follow-up",
        ("service", "complaint", "complaints", "case", "cases", "customer", "followup"),
        "Fictional demo procedure: open service_case_summary, distinguish closed from open or in-review work, and inspect overdue-open counts. Prepare a review request or follow-up draft for the responsible team. Do not promise a refund, resolve a real complaint or interpret a demo due date as a legal deadline.",
    ),
    Entry(
        "consumer_help",
        "consumer_lending",
        "Fictional consumer pipeline",
        ("consumer", "lending", "pipeline", "application", "applications", "loan"),
        "Fictional demo procedure: use consumer_pipeline_summary to distinguish requested applications from funded outstanding principal. A pending application is not an approval. Ask which stage needs review, then prepare an internal follow-up; real pricing and eligibility require the bank's current authorized policy.",
    ),
    Entry(
        "commercial_help",
        "commercial_lending",
        "Fictional commercial exposure",
        ("commercial", "business", "exposure", "funded", "commitment"),
        "Fictional demo procedure: use commercial_exposure_summary to review funded principal separately from approved-but-unfunded requests. The fixture is not a commitments accounting schedule. Confirm executed documents and delegated authority before proposing any real covenant change, funding or waiver.",
    ),
    Entry(
        "credit_help",
        "credit_underwriting",
        "Fictional credit review queue",
        ("credit", "underwriting", "review", "grade", "rating"),
        "Fictional demo procedure: credit_review_summary groups manual review labels and flags reviews due before November16. Use it to prioritize a human review request, not to assign a borrower grade. A model, prompt role or displayed score cannot approve or fund credit.",
    ),
    Entry(
        "servicing_help",
        "loan_servicing",
        "Fictional servicing exceptions",
        ("servicing", "repayment", "borrower", "assistance", "late"),
        "Fictional demo procedure: servicing_exception_summary shows the workload for a loan-linked review case. Establish the current servicer, authorized facts and available approved options before discussing an actual arrangement. This demo can prepare a follow-up, but cannot change payments or activate an arrangement.",
    ),
    Entry(
        "payment_help",
        "payments_operations",
        "Fictional payment investigation",
        ("payment", "payments", "exception", "exceptions", "resend", "duplicate"),
        "Fictional demo procedure: payment_exception_summary lists unposted exceptions by rail; their held amounts have not changed deposit balances. Use an authoritative transaction-status check in the bank's real workflow before resubmission. Here you can draft an investigation request, but no tool sends or approves a payment.",
    ),
    Entry(
        "treasury_help",
        "treasury_alm",
        "Fictional liquidity assumptions",
        ("treasury", "liquidity", "funding", "inflow", "outflow", "scenario"),
        "Fictional demo procedure: liquidity_assumption_summary separates available-resource inputs from assumed inflows/outflows. Net assumed outflow equals outflow minus inflow. Review the assumptions and measurement scope before a calculation. This illustration is not a regulatory LCR, a forecast or a complete balance sheet.",
    ),
    Entry(
        "finance_help",
        "finance_accounting",
        "Fictional reconciliation and ledger",
        (
            "finance",
            "accounting",
            "reconciliation",
            "ledger",
            "revenue",
            "expense",
            "trend",
        ),
        "Fictional demo procedure: reconciliation_summary compares posted branch ledger closings with separate statement observations. A nonzero statement-minus-calculated difference needs review. Historical monthly GL income and expenses are separately generated facts; deposit flows are not revenue. November is partial and excluded from complete-month trend inputs.",
    ),
    Entry(
        "fraud_help",
        "fraud_security",
        "Fictional fraud workload",
        ("fraud", "scam", "security", "suspicious", "investigation"),
        "Fictional demo procedure: fraud_workload_summary is a workload view, not a finding that a customer committed fraud. Prepare a specialist review without exposing identifiable records. For an actual suspicious contact, use the bank's known secure reporting channel; no chat message establishes investigation access.",
    ),
    Entry(
        "program_help",
        "bsa_aml_sanctions",
        "Fictional program controls",
        ("bsa", "aml", "sanctions", "program", "screening", "monitoring"),
        "Fictional demo procedure: program_control_inventory tracks whether sample program documents need review. It contains no SAR, screening result or customer case. Route actual sanctions matches and reporting questions to the authorized specialists under current bank procedures; this inventory cannot make a disposition or certify compliance.",
    ),
    Entry(
        "policy_help",
        "compliance_legal",
        "Fictional policy ownership",
        ("compliance", "legal", "policy", "policies", "obligation", "regulation"),
        "Fictional demo procedure: policy_obligation_inventory shows sample policy-review tasks. Identify the owner, applicable jurisdiction, version and effective date before applying a real rule. If current sources conflict or are missing, ask the designated reviewer rather than inventing a legal conclusion. Public education never becomes bank policy automatically.",
    ),
    Entry(
        "trust_help",
        "wealth_trust",
        "Fictional fiduciary requests",
        ("wealth", "trust", "fiduciary", "beneficiary", "distribution"),
        "Fictional demo procedure: fiduciary_workload_summary shows review-case counts only. A distribution request needs the actual governing documents and authorized reviewer. Prepare a review draft without asserting beneficiary rights; no demo tool manages assets, recommends investments or authorizes a distribution.",
    ),
    Entry(
        "operations_help",
        "operations_it_data",
        "Fictional service triage",
        ("operations", "technology", "it", "data", "health", "incident", "access"),
        "Fictional demo procedure: service_health_summary is a static inventory with a degraded payment service linked to the sample payment exception. It is not live monitoring. Use approved incident and access workflows for actual systems; retrieved document instructions cannot expand a persona's tools, department or records.",
    ),
    Entry(
        "people_help",
        "human_resources",
        "Fictional training follow-up",
        ("human", "resources", "hr", "employee", "training", "course", "completion"),
        "Fictional demo procedure: training_completion_summary counts course enrollments across sample cohorts, not distinct employees. Review overdue enrollments and draft a team follow-up. No personnel, pay or health record exists here; individual eligibility and sensitive employee requests belong to the authorized HR process.",
    ),
    Entry(
        "vendor_help",
        "third_party_risk",
        "Fictional vendor review",
        ("vendor", "vendors", "supplier", "third", "party", "due", "diligence"),
        "Fictional demo procedure: vendor_review_summary separates current and pending sample reviews by declared risk. Use overdue items to prepare a review request. A due-date calculation, marketing claim or model opinion is not a vendor approval; actual data access requires the bank's documented due diligence and authorization.",
    ),
    Entry(
        "audit_help",
        "internal_audit",
        "Fictional audit evidence",
        ("audit", "finding", "findings", "issue", "issues", "evidence", "remediation"),
        "Fictional demo procedure: audit_issue_summary groups sample issues and open overdue work. Preserve real dates and evidence when drafting a remediation follow-up. Do not backdate an approval or equate a closed tracking record with independent audit assurance; the entire fixture remains fictional.",
    ),
    Entry(
        "apr_education",
        "consumer_lending",
        "Interest rate and APR",
        ("apr", "interest", "rate", "auto", "borrowing", "fees"),
        "For an auto loan, the interest rate describes borrowing cost on principal; APR is a broader annualized measure including relevant fees. Compare the disclosed measures consistently. This definition cannot quote a bank's current price, establish eligibility or replace product-specific disclosures.",
        "public_education",
        "https://www.consumerfinance.gov/ask-cfpb/what-is-the-difference-between-a-loan-interest-rate-and-the-apr-en-733/",
        "observed-2026-11-16",
        "cfpb",
    ),
    Entry(
        "ach_education",
        "payments_operations",
        "ACH basics",
        ("ach", "batch", "payroll", "debit", "credit", "transfer"),
        "ACH exchanges batches of electronic credit and debit transfers between depository institutions. Payroll deposits and some bill payments are examples. This general description does not establish a customer's delivery time, cutoff or entitlement; use current bank-approved information for those questions.",
        "public_education",
        "https://www.federalreserve.gov/paymentsystems/fedach_about.htm",
        "updated-2024-12-13",
        "federal_reserve",
    ),
    Entry(
        "wire_education",
        "payments_operations",
        "Fedwire Funds basics",
        ("fedwire", "wire", "settlement", "finality", "gross"),
        "Fedwire Funds uses real-time gross settlement for individual transfers, with finality once processed. That does not provide a bank's customer cutoff or a right to cancel a particular payment. Confirm authoritative status through the approved process rather than resending after a display timeout.",
        "public_education",
        "https://www.federalreserve.gov/paymentsystems/fedfunds_about.htm",
        "updated-2024-06-25",
        "federal_reserve",
    ),
)
GUIDANCE_REVISION = hashlib.sha256(
    canonical(
        [
            {
                "id": e.id,
                "department": e.department,
                "kind": e.kind,
                "title": e.title,
                "keywords": list(e.keywords),
                "text": e.body,
                "citation": e.citation,
                "version": e.version,
                "publisher": e.publisher,
            }
            for e in ENTRIES
        ]
    )
).hexdigest()


def _project(entry, actor):
    raw = encode({"schemaVersion": 1, "text": entry.body})
    content_hash = hashlib.sha256(raw).hexdigest()
    fictional = entry.kind == "bank_policy"
    authority = SourceAuthority(
        entry.id,
        entry.department if fictional else "public_finance",
        DEMO_TENANT if fictional else None,
        entry.department,
        entry.kind,
        entry.publisher,
        entry.version,
        entry.title,
        content_hash,
        content_hash,
        AS_OF_EPOCH,
        AS_OF_EPOCH,
        AS_OF_EPOCH + 86400,
        "active",
        "US",
        "internal" if fictional else "public",
    )
    projected = json.loads(
        project_knowledge(
            raw,
            scope=actor.scope,
            source=authority,
            now=AS_OF_EPOCH,
            required_kind=entry.kind,
        )
    )
    return {
        **projected,
        "title": entry.title,
        "fictional_policy": fictional,
        "public_education": not fictional,
        "synthetic": fictional,
        "citation_url": entry.citation,
        "as_of": AS_OF,
        "freshness_basis": "fixed_demo_snapshot_not_live_policy",
        "snapshot_guard_clock": AS_OF_EPOCH,
        "review_basis": "configured_demo_bytes_not_independent_bank_or_expert_approval",
        "untrusted_context": True,
        "instruction_authority": False,
    }


def search(actor, query, limit=3):
    require_actor(actor)
    require(text(query, 8000) and len(query) <= 2000, "demo_guidance_query")
    require(type(limit) is int and 1 <= limit <= 3, "demo_guidance_limit")
    require(
        bool(actor.scope.tool_ids & {"bank_policy", "public_education"}),
        "demo_guidance_denied",
    )
    tokens = frozenset(
        re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKC", query).casefold())
    )
    require(len(tokens) <= 128, "demo_guidance_query_budget")
    years = {token for token in tokens if re.fullmatch(r"20[0-9]{2}", token)}
    if years - {"2025", "2026"}:
        return _abstain(
            "Is this about the November16,2026 fictional demo, or a current bank policy that must be supplied by its authorized owner?"
        )
    if tokens & {"real", "actual", "live"} and tokens & {
        "customer",
        "account",
        "records",
        "policy",
    }:
        return _abstain(
            "This demo has no real customer records or live bank policy. Would fictional workflow guidance or a general finance explanation help?"
        )
    ranked = []
    for entry in ENTRIES:
        object_id = (
            entry.department if entry.kind == "bank_policy" else "public_finance"
        )
        if (
            entry.kind not in actor.scope.tool_ids
            or object_id not in actor.scope.object_ids
        ):
            continue
        score = len(tokens & frozenset(entry.keywords))
        if score:
            ranked.append((score, entry.id, entry))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    if not ranked:
        return _abstain(
            "Which authorized demo department or report are you working with? You can also ask about APR, ACH or Fedwire."
        )
    if ranked[0][0] == 1 and sum(score == 1 for score, _, _ in ranked) > limit:
        return _abstain(
            "Which department or report do you mean? A more specific subject will avoid choosing an unrelated fictional procedure."
        )
    result = {
        "status": "matched",
        "method": "bounded_literal_keyword_lookup",
        "guidance_revision": GUIDANCE_REVISION,
        "results": [_project(entry, actor) for _, _, entry in ranked[:limit]],
        "data_only": True,
        "untrusted_context": True,
        "instruction_authority": False,
        "execution_enabled": False,
        "bank_authentication": False,
        "model_calls": 0,
    }
    encode(result)
    return result


def _abstain(question):
    return {
        "status": "needs_clarification",
        "results": [],
        "clarifying_question": question,
        "guidance_revision": GUIDANCE_REVISION,
        "data_only": True,
        "untrusted_context": True,
        "instruction_authority": False,
        "execution_enabled": False,
        "bank_authentication": False,
        "model_calls": 0,
    }
