"""Planning coverage and closed report names; nothing here grants access."""

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class Department:
    id: str
    label: str
    curriculum: str


DEPARTMENTS = (
    Department(
        "retail_deposits",
        "Branch and deposits",
        "Deposit products, insurance concepts and account servicing boundaries",
    ),
    Department(
        "customer_service",
        "Customer service",
        "Explain products, complaints, accessibility and escalation",
    ),
    Department(
        "consumer_lending",
        "Consumer lending",
        "Loan terminology, disclosures and fair treatment",
    ),
    Department(
        "commercial_lending",
        "Commercial lending",
        "Commercial credit structure and borrower financial statements",
    ),
    Department(
        "credit_underwriting",
        "Credit and underwriting",
        "Credit analysis concepts and limits on automated decisions",
    ),
    Department(
        "loan_servicing",
        "Loan servicing",
        "Servicing concepts, payment allocation and borrower assistance",
    ),
    Department(
        "payments_operations",
        "Payments operations",
        "Payment rails, settlement, exceptions and investigation",
    ),
    Department(
        "treasury_alm",
        "Treasury and asset/liability management",
        "Liquidity, interest-rate exposure and scenario assumptions",
    ),
    Department(
        "finance_accounting",
        "Finance and accounting",
        "Statements, reconciliations, balances and reporting definitions",
    ),
    Department(
        "fraud_security",
        "Fraud and security",
        "Fraud warning signs, account protection and escalation",
    ),
    Department(
        "bsa_aml_sanctions",
        "BSA, AML and sanctions",
        "Program concepts, confidentiality and specialist escalation",
    ),
    Department(
        "compliance_legal",
        "Compliance and legal",
        "Locate authoritative guidance and applicable bank policy",
    ),
    Department(
        "wealth_trust",
        "Wealth and trust",
        "Fiduciary concepts, conflicts and specialist advice boundaries",
    ),
    Department(
        "operations_it_data",
        "Operations, IT and data",
        "Access, resilience, data quality and incident triage",
    ),
    Department(
        "human_resources",
        "People operations",
        "Employee privacy, training and approved internal policy",
    ),
    Department(
        "third_party_risk",
        "Third-party risk",
        "Due diligence, contracts, monitoring and exit planning",
    ),
    Department(
        "internal_audit",
        "Internal audit",
        "Evidence, independence, findings and remediation tracking",
    ),
)
DEPARTMENT_IDS = frozenset(item.id for item in DEPARTMENTS)
# These names describe future bank-reviewed aggregate adapters, not live tools,
# columns, SQL, customer records, approvals or currently available bank reports.
REPORTS = MappingProxyType(
    {
        "deposit_portfolio_summary": "retail_deposits",
        "service_case_summary": "customer_service",
        "consumer_pipeline_summary": "consumer_lending",
        "commercial_exposure_summary": "commercial_lending",
        "credit_review_summary": "credit_underwriting",
        "servicing_exception_summary": "loan_servicing",
        "payment_exception_summary": "payments_operations",
        "liquidity_assumption_summary": "treasury_alm",
        "reconciliation_summary": "finance_accounting",
        "fraud_workload_summary": "fraud_security",
        "program_control_inventory": "bsa_aml_sanctions",
        "policy_obligation_inventory": "compliance_legal",
        "fiduciary_workload_summary": "wealth_trust",
        "service_health_summary": "operations_it_data",
        "training_completion_summary": "human_resources",
        "vendor_review_summary": "third_party_risk",
        "audit_issue_summary": "internal_audit",
    }
)
REPORT_IDS = frozenset(REPORTS)
TOOL_IDS = frozenset(
    {"public_education", "bank_policy", "read_report", "prepare_proposal"}
)
ACTION_IDS = frozenset({"request_internal_review", "draft_internal_followup"})
