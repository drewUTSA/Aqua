# Banking companion and MCP foundation

This is a pure offline contract slice for a possible U.S. bank companion. It adds no runtime route, MCP server, SDK, connector, model call, database schema, training run or application dependency. No bank has been onboarded. It does not establish authentication, approval durability, banking expertise, regulatory compliance or deployment readiness. Aqua's existing sample dataset named `bank` is not a bank tenant.

The source is under `eval/banking/`; synthetic contract tests are under `tools/checks/test_banking*.py`. The existing Aqua executor, SQL validator, restricted workers, hybrid/compiler and retriever remain the integration points to evaluate later. This slice does not duplicate them or expand their authority.

## Boundaries implemented

`trusted_scope` accepts only caller-supplied canonical bank-tenant and principal UUIDs, an authorization revision, and closed object, tool and report grants. Empty grants deny access. A future authenticated bank adapter must derive these values from the bank's identity and authorization systems at each operation. A prompt, email address, department name, hash or Python dataclass cannot establish that authority. Tool names, report names and department coverage are planning metadata, not permissions. Object grants are independent of report and tool grants.

`SourceAuthority` separates `public_education` from `bank_policy`. Projection requires a matching tool and object grant, a known department, U.S. jurisdiction, an active lifecycle, effective and unexpired metadata, a publisher/document version/section citation, and exact reviewed content bytes. A public source has no bank tenant and is classified public; bank policy must match the caller's tenant and be internal or restricted. Public education cannot satisfy a bank-policy request. Draft, superseded, unknown, stale, future-effective or changed source declarations are denied.

These declarations are not signed attestations. The matching `reviewed_sha256` records byte agreement; it does not establish reviewer identity, source ownership, rights, policy approval or that a registry contains no conflicting policy. A future registry must independently verify publisher and bank approval, retain the original citation URL and review evidence, resolve supersession/conflicts, and refresh/revoke declarations. Missing, conflicting or stale policy requires abstention and bank escalation. This module returns cited data; it does not decide an employee's legal or operational answer.

`ReportArtifact` binds a closed report ID and artifact ID to a tenant, scoped object, source revision/version, observation time and expiry. `select_report` returns a read-only advisory reference. It produces no rows, SQL, URLs, file paths or requests. The 17 report IDs are names for possible future bank-reviewed aggregate adapters; they do not prove those reports exist. Sensitive cases, customer records, employee records and SAR content have not been authorized by creating a catalog entry.

`create_proposal` supports only `request_internal_review` and `draft_internal_followup`. Its exact canonical payload is bound to the tenant, principal, entire scope fingerprint and authorization revision, report/artifact/object references, source revision/version, creation time and expiry. Rechecking requires the same canonical payload and fresh caller scope/artifact inputs. Even unrelated scope expansion invalidates the old draft. JSON formatting can vary before canonicalization; the user's note is not trimmed or silently rewritten.

Every proposal remains `proposal_only`, with `requires_human_approval=true`, `approval_recorded=false` and `execution_enabled=false`. There is no approve or execute API, storage, signature, approval token, maker/checker workflow or execution transition. SHA-256 detects byte changes against the supplied digest; a person able to replace bytes and recompute that digest can construct another inert draft. It is not forgery resistance, an approval credential or one-use/replay enforcement. Neither a successful recheck nor self-declared approval becomes permission to act.

## Offline limits

The parser accepts only UTF-8 JSON bytes up to 32 KiB, exact fields, finite values and distinct keys. Canonical output is also bounded to 32 KiB. Identifiers are limited to 64 characters; policy text is limited to 4,096 UTF-8 bytes and proposal notes to 1,024 bytes. Text rejects control/format/surrogate characters except LF and TAB where multiline text is explicitly allowed. Version and timestamp fields reject booleans. Errors contain fixed categories rather than input content.

Source declarations have a maximum 24-hour lease; report and proposal declarations have maximum five-minute leases. These are conservative **offline test-contract budgets**, not bank-approved freshness rules, wall-clock synchronization, legal retention periods or production defaults. Registry revocation, authorization refresh and trusted time must be implemented and reviewed before runtime use. The bank must determine appropriate freshness for each task and source.

## Department learning and evaluation plan

The 17-area catalog is a coverage plan, not a claim that every bank department is supported. Each public topic below is bounded by the named source catalog's support limits; bank-specific columns describe information this application does not yet possess. No bank policy, customer data, private GH corpus or personnel record is included.

| Department ID | Public education candidate | Bank-specific evidence required before operational answers |
| --- | --- | --- |
| `retail_deposits` | FDIC deposit and insurance concepts (`fdic-deposits`) | Product terms, ownership facts, account authority and approved disclosure procedures |
| `customer_service` | Relevant complaint facts and authorization (`cfpb-complaints`) | Complaint routing, response standards, accessibility procedures and customer permissions |
| `consumer_lending` | Interest rate versus APR in the source's auto-loan context (`cfpb-apr`) | Product-specific disclosures, fees, underwriting and decision authority |
| `commercial_lending` | Commercial loan and portfolio concepts (`occ-commercial`, `occ-portfolio-2026`) | Current credit policy, borrower definitions, covenants and delegated limits |
| `credit_underwriting` | Identifying and rating credit risk (`occ-credit-rating`, `occ-portfolio-2026`) | Approved rating scale, validation, fair-lending review and human decisions |
| `loan_servicing` | Mortgage lender versus servicer (`cfpb-servicer`) | Loan-specific terms, payment allocation, borrower assistance and complaint policy |
| `payments_operations` | ACH batches and Fedwire settlement concepts (`fed-ach`, `fed-fedwire`) | Current rail procedures, cutoffs, return/recall conditions and authorized payment workflow |
| `treasury_alm` | Rate exposure and liquidity concepts (`occ-interest-risk`, `occ-liquidity`) | Assumptions, balances, scenarios, approved limits and ALCO governance |
| `finance_accounting` | What BAAS interpretations represent (`occ-accounting-2026`) | Approved accounting policy, ledger definitions, reconciliations and reporting control evidence |
| `fraud_security` | Bank impersonation and independent verification (`fdic-impersonation`) | Incident procedures, investigation entitlements and restricted case evidence |
| `bsa_aml_sanctions` | FinCEN mission and potential name-match review (`fincen-mission`, `ofac-match`) | Current bank procedures, specialist decisions, confidentiality and restricted evidence controls |
| `compliance_legal` | Identify the current Regulation B source (`cfpb-reg-b`) | Applicability, current legal interpretation, approved bank policies and escalation owner |
| `wealth_trust` | Personal fiduciary activity concepts (`occ-fiduciary`) | Governing instruments, conflicts, duties, entitlements and specialist advice |
| `operations_it_data` | Information security and authentication concepts (`fed-info-security`, `fed-auth-2021`) | Bank access architecture, service owners, incident/resilience procedures and data lineage |
| `human_resources` | Customer-information staff training concepts (`fed-info-security`) | Bank employment policies, employee privacy, HR entitlements and training requirements |
| `third_party_risk` | Risk-based relationship lifecycle (`fed-third-party`) | Vendor inventory, risk tiering, contracts, monitoring and approved exit plans |
| `internal_audit` | Audit function and independence concepts (`occ-audit`) | Audit charter, evidence custody, findings workflow and independent assurance |

The separate workspace candidate packet is `training/bank-public-review-20261116/`. Its `source-catalog.json` records 21 official sources, observed versions/sections, links, support limits and rights caveats. Its `source-verification.json` records response-body hashes without copying pages into this application. The proposed 48 original QA candidates and 36/12 split remain **unapproved**, without banking expert review or a training run. They are not imported by this module. Official public availability does not by itself approve training rights. The prior approval for 25 Aqua SQL examples does not approve this new packet.

Concrete next steps for learning and evaluation are:

1. Have bank subject-matter owners review each candidate's facts, applicability, citation, version, rights and answer limits. Keep public education separate from approved tenant policy. Do not infer a bank's procedures from a handbook, general FAQ or another bank's practice.
2. Ingest bank policy only through an approved future registry with tenant/classification/object grants, exact document hash and section, issuer and human-review evidence, effective/expiry dates, supersession/conflict handling and revocation. Retrieved text remains untrusted data, including instructions embedded inside documents.
3. Create a new reviewed evaluation split before model experiments. Cover each department plus missing/stale/conflicting policy, citation accuracy, uncertainty, prompt role claims, tenant/actor/object/tool isolation and a refusal to decide unauthorized consequential actions. Keep these cases separate from training and from Aqua's protected 67 SQL cases and both earlier 16-case research packets. Do not reuse those failures to tune a candidate.
4. Evaluate permissioned report selection on synthetic artifacts first. Evaluate numeric questions against deterministic, independently checked calculations with explicit units, as-of times, assumptions, rounding and definitions; no calculator is added in this slice. Measure citation support, correct abstention and task accuracy separately from authorization failures.
5. Compare a fixed baseline and each candidate on all attempts, including refusals, errors, latency and source freshness. Use bank expert review for operational usefulness and a new held-out set for quality. The pure tests below prove contract behavior only; they do not establish model knowledge, companionship, calibration or production security.
6. Require an explicit reviewed packet and approval for any later training/export. The rejected earlier Aqua adapter stays rejected. No protected failures, private corpora, automatic online learning, customer conversations or employee records are training material by default. Keep model weights, dataset assets and caches out of public application history.

## Governance references and applicability

The separate workspace review `context/BANK_SECURITY_GAP_REVIEW_20261116.md` records source observations and remaining gaps. Relevant primary references include [FFIEC authentication guidance (August 11, 2021)](https://www.ffiec.gov/sites/default/files/media/press-releases/2021/authentication-and-access-to-financial-institution-services-and-systems.pdf), the [Federal Reserve information-security small-entity guide](https://www.federalreserve.gov/supervisionreg/interagencyguidelines.htm), [interagency third-party risk guidance, SR 23-4](https://www.federalreserve.gov/supervisionreg/srletters/SR2304.htm), and [NIST AI 600-1](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence). These inform review questions; they do not certify Aqua or replace governing requirements and bank counsel.

The [April 2026 interagency model-risk guidance attachment](https://www.federalreserve.gov/supervisionreg/srletters/sr2602a1.pdf) explicitly excludes generative and agentic AI from its scope in footnote 3. Do not claim that this guidance directly governs or certifies this proposed generative companion. Source applicability and any future changes require fresh review.

## Integration and release gates

The MCP **2026-07-28** transport and authorization requirements remain future integration work. No MCP SDK or server is added here. A real adapter requires protocol/version negotiation, the required HTTP transport behavior, OAuth resource-server validation and bank IdP integration; the [official MCP specification](https://modelcontextprotocol.io/specification/2026-07-28) must be rechecked at implementation. Department labels and prompts must never substitute for authenticated tenant/principal mapping or current object-level grants. Do not forward tokens to unapproved downstream resources or treat a client-supplied tenant as verified.

A production proposal system needs independently authenticated reviewers and a bank-approved separation-of-duties policy, durable append-only approval/audit records bound to the exact payload and source/scope revisions, revocation and expiry handling, and reapproval after any relevant change. A separate connector executor must check the durable approval, authority and source again, enforce idempotency and narrow bank actions, reconcile outcomes, and preserve failures. Those requirements are absent here; no generated draft can execute.

Real bank platform connectors, approved policy ingestion, retrieval permissions, deterministic financial calculation tools, secret handling, retention/deletion, customer and employee privacy, bank audit review, incident controls, adversarial runtime validation and staged bank pilot acceptance are still required. This code does not resolve Aqua's existing external analytical-database DNS/access issue or other release gates. No runtime deployment or consequential bank action is authorized by this document.

## Verification

Run the source-only synthetic tests from the application checkout:

```powershell
../.venv/Scripts/python.exe -m unittest discover -s tools/checks -p 'test_banking*.py' -v
```

The tests cover missing and malformed grants, tenant/principal/revision changes, object/tool/report denial, prompt role claims, stale/superseded sources, exact reviewed bytes, unknown/duplicate fields, input budgets, canonical payload mutation, expiry, and self-declared approval flags. They require no database, provider, credentials, Docker or network connection.
