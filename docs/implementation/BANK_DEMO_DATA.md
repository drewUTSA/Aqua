# Fictional bank demo data and guidance

This is an original, deterministic **sales demonstration** for a fictional U.S.
bank called Aqua Harbor Demo Bank. It is not a bank, an FDIC-insured institution,
a commercial-bank integration or an authorization system. No actual people,
customer records, account numbers, addresses, emails, SSNs, private company
documents, CTU/Berka rows or model-generated customer facts are included.

The fixture and fictional procedures were authored for Aqua under the user's
instruction. No third-party dataset or policy document was copied. Three short
general-finance explanations cite official public sources; their inclusion does
not turn them into a specific bank's approved policy. This work does not approve,
export or train on the separate48-example candidate learning packet, alter
weights or activate the previously rejected adapter. Root review of the source
bytes and demonstration remains required before presentation.

## Immutable source and dates

`mcp_demo/fixtures/bank.json` contains the complete small fixture. `data.py` checks
its closed structure, amounts, references, monthly completeness and canonical
SHA256, then exposes deeply immutable mappings/tuples. Its canonical data revision
is `8c27aa965ae4087fc965f66957ab08dde9b18de1cf6abdd321102afb6f8cdd37`.
Canonicalization uses sorted-key compact UTF-8 JSON with no floating numbers;
whitespace changes do not change the data revision. A changed fact does and
requires a deliberate pin/review update. No environment, URL, file path or caller
dataset can replace this fixture through a tool argument.

All operational facts use USD and the **November1–16,2026 partial-month snapshot**.
The17 operational reports accept only `period="2026-11"`, `currency="USD"`; other
months/currencies are rejected rather than reconstructing historical loan or
control statuses that were never recorded. Every report labels the source,
as-of date, partial period, synthetic origin and lack of actual bank authentication.

Historical GL facts are separately synthetic by construction:18 complete months
from May2025 through October2026 plus explicitly partial November2026. These
historical ledger records do not backfill the operational statuses. They are
complete only for the defined three-category fixture scope, not for a real bank's
books. The fixture is not a complete balance sheet or GAAP financial statement.

## Coherent source families and report definitions

Seven deposit buckets contain fictional branch/product balances and6,050 account
counts. Twelve dated transactions link to those buckets. Ten posted events change
balances; two exception events do not. Six consumer/commercial loan records
separate requested amounts, stages, outstanding funded principal and manual
review labels. Eight cases link to a deposit bucket, transaction, loan or control.
Controls, training cohorts, vendors, services and audit tracking records form the
remaining small internally referenced source families. No source family contains
individual customer or employee rows.

The17 report IDs come directly from the existing closed banking catalog:

| Report | Derivation and limit |
| --- | --- |
| `deposit_portfolio_summary` | Bucket opening cents + posted deposits − posted withdrawals, grouped by fictional branch/product. |
| `service_case_summary` | Customer-service case counts by status/priority; open overdue is due before November16. |
| `consumer_pipeline_summary` | Consumer loan records by stage, keeping requested and funded outstanding amounts separate. |
| `commercial_exposure_summary` | Equivalent commercial aggregation; approved-but-unfunded is not outstanding exposure. |
| `credit_review_summary` | Manual fixture review labels and overdue reviews; no inferred rating or credit approval. |
| `servicing_exception_summary` | Loan-linked servicing case workload; no borrower disclosure or change to payment terms. |
| `payment_exception_summary` | Unposted exception transactions by rail and held amount; no payment instruction. |
| `liquidity_assumption_summary` | Resource/inflow/outflow assumptions and outflow minus inflow; not a regulatory LCR or solvency conclusion. |
| `reconciliation_summary` | Branch ledger versus separate statement observations; statement minus calculated closing is the difference. |
| `fraud_workload_summary` | Fraud-team case workload, without accusing any customer of fraud. |
| `program_control_inventory` | Fictional BSA/AML/sanctions program-document review inventory, with no actual SAR or screening case. |
| `policy_obligation_inventory` | Fictional compliance-policy review tasks, without a legal conclusion or compliance certification. |
| `fiduciary_workload_summary` | Fiduciary review-case counts, without trust assets or distribution authority. |
| `service_health_summary` | Static service status and linked open incidents; no live monitoring claim. |
| `training_completion_summary` | Course enrollments across aggregate cohorts, not distinct employees. |
| `vendor_review_summary` | Vendor count by declared risk/review status and overdue review dates; not vendor approval. |
| `audit_issue_summary` | Issue tracking by severity/status and overdue open work; not independent audit assurance. |

Amounts are integer cents in the fixture and exact two-decimal USD strings in
results. No binary floating arithmetic is used. Results contain bounded aggregate
tables, literal definitions and provenance, never raw row IDs, SQL, a connection
string or customer details. The account counts are synthetic bucket inputs, not
customer-record enumeration.

Useful independent check values: deposit closing total **9,628,750.00USD**;
exception holds **8,450.00USD** excluded from that total; central-branch statement
minus calculated closing **250.00USD**, with north/south zero. The deliberately
nonzero statement observation supports a practical review workflow rather than
pretending every sample is reconciled. It does not authorize a correcting entry.

## Monthly inputs for separately qualified trend learning

`reports.get_monthly_series(actor, metric_id)` accepts no rows, metadata, source
URL or arbitrary metric expression. It rechecks the canonical actor and the
finance/reconciliation report/tool/object grants before deriving these closed
metrics from the internal ledger:

- `gl_operating_income`: monthly SUM of fictional interest income + fee income;
  this is gross specified income, not net income and not deposit flows.
- `gl_operating_expense`: monthly SUM of the stated operating-expense category,
  represented as positive costs.
- `gl_operating_surplus`: the first minus the second, excluding tax, provisions
  and all other unmodeled items. This is not GAAP net income.

Each month contains exactly one entry for each of the three categories.
The helper returns18 consecutive first-of-month periods with exact decimal text,
`unit="USD"`, `aggregation="monthly_sum"`, `complete=true`, `truncated=false`,
source definition/origin/as-of metadata and `excluded_partial_periods=["2026-11"]`.
May2025 income/expense/surplus is195,000.00/150,000.00/45,000.00USD; October2026
is357,000.00/208,000.00/149,000.00USD. These are authored demonstration facts.

`dataset_revision` binds the entire canonical fixture. `source_revision` hashes
the exact returned series/definition/provenance metadata before that hash field
is added. Caller scope is separately bound by the server, rather than changing a
dataset's identity for each persona. Root can normalize these internally trusted
inputs to the existing monthly-trend contract and preserve its minimum12 points
and rolling-origin evidence requirements. This module does not fit a trend,
forecast, call a model or claim improved model weights. Any later trend tool must
report its actual evaluation, baseline comparison and limitations separately.

## Permissions and inert proposals

Only the server launch selects a fixed persona. `protocol.require_actor` validates
the frozen `DemoActor(persona, BankScope)` against its canonical registry; a
request cannot supply a tenant, department, role or replacement scope. The teller
has branch/deposit and customer-service aggregate reports; analyst has finance,
treasury, credit review and commercial lending; manager has all17. The none
persona has no report/guidance authority. These are static demo entitlements,
not workforce SSO/MFA, actual bank tenant isolation or customer-record permissions.

`reports.artifact_for` reuses the existing `ReportArtifact` checks for tenant,
report/tool/object membership, source revision and a five-minute server-clock
lease. It supplies source-bound references to a separate inert proposal path.
The result cannot approve a proposal or execute a bank action; the existing
proposal contract still requires a human and records no approval/executor.

## Guidance and retrieval

`guidance.py` provides17 original fictional workflow procedures and three general
education entries. They give practical steps: inspect the appropriate authorized
report, distinguish the relevant metric/status, clarify missing facts, and prepare
a review/follow-up draft when appropriate. Unsupported real policies, individual
records and future-date requests produce a useful clarification instead of a
fabricated answer. All choices remain inside the persona's available objects.

The only external sources are the [CFPB auto-loan APR explanation](https://www.consumerfinance.gov/ask-cfpb/what-is-the-difference-between-a-loan-interest-rate-and-the-apr-en-733/),
[Federal Reserve ACH overview](https://www.federalreserve.gov/paymentsystems/fedach_about.htm)
and [Fedwire Funds overview](https://www.federalreserve.gov/paymentsystems/fedfunds_about.htm).
Their citations/observed or published version labels are fixed source metadata;
no tool fetches those URLs. They are short original explanations, with no copied
source corpus, live rate, current bank cutoff or individual advice claim.

Search is a small bounded literal keyword lookup, with no embedding/vector store,
provider or model planner. The existing Aqua-help keyword pack has closed
product-specific topics, so it is not relabeled as banking knowledge. Projection
does reuse `SourceAuthority`/`project_knowledge` and its source-kind, byte-hash,
tenant/object/tool and data-only boundaries. Fictional policy results explicitly
say `fictional_policy=true`; public education never becomes an approved bank
policy. All results are untrusted context data for a consumer model, not system
instructions or permission to execute tools.

The source guard deliberately runs on the labelled **fixed demo snapshot clock**
November16,2026, not the wall clock, and reports that fact. It does not claim a
source was revalidated today or that a real policy is currently effective. The
matching review/content hash is a configured demo-byte declaration, not an
independent expert/bank approval. An actual bank deployment needs a live trusted
source registry, owners, review/expiry/revocation and current authenticated scope.

## Scope of this source slice

These modules use only fixed local data and pure calculations. They do not create
or connect to PostgreSQL, read `.env`, contact Tiger/CTU, acquire datasets, alter
backend dependencies/runtime/P11 pins, change the existing UI, store memory or
send notifications. A future optional PostgreSQL adapter should use the already
chosen separate analytical PostgreSQL service and the same fixture revision and
closed reports; no additional database engine is implied. Qualify it separately
before describing in-memory results as database-backed behavior.
