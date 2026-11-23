# Local fictional bank MCP demonstration

### Prepare an offline demo for an employee

From a trusted Aqua checkout, run `python tools/bank_demo/build_offline_demo.py ../aqua-bank-demo-transfer` with a new output directory. The builder takes the reviewed bank sources, fixtures, launchers and wheel locks from the current Git commit and retrieves only hash-pinned wheels. Give the employee the resulting ZIP and its SHA-256 through your usual trusted handoff.

On Windows x64 or glibc Linux x86_64, the employee needs CPython 3.12 with venv support. Setup in the extracted folder installs locally with package indexes disabled and prints an MCP host entry. The included teller, analyst and manager walkthroughs run without a database login, cloud account or model download. [Offline installation and employee roles](../../tools/bank_demo/offline/README.md)

This is a runnable **sales demonstration using original synthetic bank data**.
An MCP host can discover scoped aggregate reports, receive cited fictional
guidance, perform exact financial calculations, inspect descriptive monthly
trends and prepare an inert review proposal. It connects to no real bank,
customer account, identity provider, model provider or production Aqua database.
It is not a compliance certification, trained banking model, bank authorization
system or durable human-approval workflow.

When a host lists the tools, the report and proposal input schemas offer the
same report IDs as the employee's authorized catalog. The fictional teller
can choose two reports, the analyst four and the manager seventeen. The server
also checks the employee's scope when a tool is called.

The stdio module and SDK dependency lock remain separate from the application
backend. The optional [report web increment](BANK_DEMO_WEB_CONTRACT.md) packages
only the explicitly reviewed SDK-free report core; it does not run the MCP
transport or install the SDK in the backend.

Running the stdio module does not upgrade the backend, change the live site,
migrate a database or install configuration into an MCP host. Existing failed
Ollama tool-selection experiments remain unqualified; the server does not enable
an autonomous planner.

## Isolated installation

Use CPython3.12 on Windows x64 or Linux x86_64. From the repository root, create
the dedicated ignored environment rather than reusing the application environment.
The bootstrap lock updates only that environment's installer; the runtime lock
contains the29 SDK dependencies. Both use exact wheel hashes.

Windows PowerShell:

```powershell
py -3.12 -m venv .venv-bank-demo
.venv-bank-demo/Scripts/python.exe -m pip install --require-hashes -r tools/bank_demo/requirements-bootstrap.txt
.venv-bank-demo/Scripts/python.exe -m pip install --require-hashes -r tools/bank_demo/requirements-lock.txt
.venv-bank-demo/Scripts/python.exe -m pip check
.venv-bank-demo/Scripts/python.exe -B -m unittest discover -s tools/bank_demo -p 'test_*.py'
```

Linux:

```bash
python3.12 -m venv .venv-bank-demo
.venv-bank-demo/bin/python -m pip install --require-hashes -r tools/bank_demo/requirements-bootstrap.txt
.venv-bank-demo/bin/python -m pip install --require-hashes -r tools/bank_demo/requirements-lock.txt
.venv-bank-demo/bin/python -m pip check
.venv-bank-demo/bin/python -B -m unittest discover -s tools/bank_demo -p 'test_*.py'
```

The runtime is pinned to official Python SDK `mcp==2.3.0`; the launcher rejects a
different installed SDK version. That version supports the2026-07-28 protocol and
legacy handshake clients. The public low-level `Server`, official `stdio_server`
and official client own MCP dispatch, framing and version negotiation. The small
adapters enforce local input/output bounds and a strict JSON safety check before
the official parser, without implementing JSON-RPC dispatch or negotiation.
See the [official release history](https://github.com/modelcontextprotocol/python-sdk/releases)
and [v2 migration guidance](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/migration.md).

The selected SDK version is newer than the2.2.0 fix for
[GHSA-qx49-fqc8-xw99](https://github.com/modelcontextprotocol/python-sdk/security/advisories/GHSA-qx49-fqc8-xw99).
That advisory addresses HTTP OAuth client credential forwarding; this server
offers local stdio only. The separately pinned `pip==26.3` bootstrap addresses
installer findings from the fresh environment's older bundled pip. Installer and
runtime audits are separate evidence; no audit establishes permanent immunity to
future vulnerabilities.

## Launch from an MCP host

Configure an explicitly approved local MCP host to start this command in the
repository root:

```powershell
.venv-bank-demo/Scripts/python.exe -B -m mcp_demo --persona analyst
```

Supply the absolute executable path and absolute repository working directory
when the host requires them. For example, a host supporting `command`, `args`
and `cwd` can use the following server entry after adapting the checkout path:

```json
{
  "command": "C:/Users/Ben/Documents/ChatGPT/Aqua_final/app-mcp-demo/.venv-bank-demo/Scripts/python.exe",
  "args": ["-B", "-m", "mcp_demo", "--persona", "analyst"],
  "cwd": "C:/Users/Ben/Documents/ChatGPT/Aqua_final/app-mcp-demo"
}
```

The server expects MCP messages on standard input. An ordinary terminal launch
waits for that input; it is not an interactive chat interface or HTTP service.
The host owns process lifetime and should stop the child on disconnect. No
client commands, shell tools or outbound model calls are executed by the server.
Passing a persona in a chat prompt or tool argument cannot change process scope.

| Host-selected persona | Fictional report scope |
| --- | --- |
| Omitted | Context only; empty data/tool grants. |
| `teller` | Retail deposits and customer service. |
| `analyst` | Finance/accounting, treasury/ALM, credit underwriting and commercial lending. |
| `manager` | All17 fictional aggregate departments. |

These are fixed demonstration personas, not authenticated bank employee roles.
The shared synthetic tenant UUID and registry are not credentials. Real bank
identity, authorization and record ownership require a separately qualified
adapter; the model must never supply them as trusted authority.

## Available work

Every successful or denied tool result includes `synthetic=true`,
`demo_only=true`, the fixture `sourceRevision`, `asOf=2026-11-16`, US/USD context,
`execution_enabled=false` and `approval_recorded=false`. Text and structured
content carry the same envelope for older and newer hosts.

| Tool | Behavior |
| --- | --- |
| `demo_context` | Explains the fixed persona, permitted reports, tools and fictional scope. |
| `list_authorized_reports` | Lists aggregate reports permitted by that process persona. |
| `run_demo_report` | Reads one of the17 closed catalog IDs within scope. November2026 only; USD only; no SQL or caller-provided rows. |
| `search_demo_guidance` | Bounded literal retrieval with citations. Fictional procedures remain separate from public financial education and never become real bank policy. |
| `calculate_finance` | Deterministic Decimal simple interest, amortizing payment, percent change, liquidity coverage or reconciliation. Numeric fields are bounded plain strings; floats, booleans and unknown fields are denied. |
| `prepare_review_proposal` | Produces an exact unapproved draft bound to a current authorized report and expected fixture revision. It creates no approval record and can execute nothing. |
| `analyze_monthly_trend` | Uses an authorized fixed GL series to fit and chronologically evaluate descriptive trends. Available to analyst/manager; no forecasts, causality, neural training or promotion claim. |

The finance tool's discovered schema couples each operation to its required
closed parameter object, plain numeric-string bounds, USD/period constraints
and a valid example; runtime validation remains independent.

Each authorized report also includes a bounded `companion_brief`: its exact
definition, partial-period caveats, one canonical cited fictional procedure and
three inert human next-step suggestions. Report, department, fixture revision,
guidance revision and fixed as-of date stay bound together. A missing grant or
stale source cannot substitute another department's procedure. Suggestions carry
no executable tool arguments; preparing an unapproved review draft remains a
separate explicit request. No model, memory or additional MCP tool is involved.

The18 complete fictional monthly GL points cover May2025–October2026. Partial
November is excluded from fitting. The three metric IDs are
`gl_operating_income`, `gl_operating_expense` and `gl_operating_surplus`; callers
cannot replace the rows, units or completeness flags. Existing trend qualification
remains false. Operational November reports are separate from this historical GL
fixture. See [data definitions and limitations](BANK_DEMO_DATA.md).

For a first walkthrough, ask the host to call `demo_context`, list authorized
reports, run `reconciliation_summary` as analyst, examine the surplus trend and
explain its measured holdout limitations. To prepare a review draft, pass the
`sourceRevision` returned by context as `expected_source_revision` and supply a
fictional note. The resulting proposal is source-bound data, not an approved act.
Do not enter real customer or employee information into this demonstration.

## Bounds and error handling

Input and output MCP frames are limited to32KiB, including serialized result
overhead. Tool arguments are limited to8KiB; payloads and strings have additional
closed limits. The JSON safety check rejects duplicate decoded field names
(including escaped equivalents), more than32 container levels, more than4,096
value/container nodes, numeric tokens longer than64 characters and nonfinite
numbers. JSON string contents are decoded normally; braces inside a string do
not count as nesting. There is one admitted tool handler at a time. The two-second
async deadline cooperatively cancels awaitable work, and a monotonic check rejects
a synchronous result that finishes late. This does **not** physically preempt
CPU work: the17-report fixture,18-point trends and maximum600-month calculator
work are separately finite. No arbitrary SQL, file, network or shell operation
is a tool.

An unsafe JSON frame, oversized frame, invalid UTF-8 or EOF without a newline
terminates the input session with a fixed diagnostic. Negotiation revisions
must come from the pinned SDK's public revision registry: unknown values are
rejected before the SDK can reflect them in a negotiation error. The SDK still
selects and serves the protocol era for admitted messages. An open pipe with an
incomplete line can wait for the local host; there
is no idle timeout or claim of autonomous thread cancellation. A host can
terminate its child process. Errors use fixed categories; validation input and
external exception strings are not returned or logged by this server. SDK parse
exceptions are scrubbed before dispatch. Stdout is reserved for MCP, with
diagnostic logging disabled and fixed top-level stderr messages. This is a
process-level implementation boundary, not an operating-system sandbox.

Tool annotations are advisory metadata. Canonical server-selected scopes and
per-report checks enforce the demonstration boundary. The server has no approve,
execute, payment, email, file, shell or arbitrary URL tool, no durable state and
no HTTP/OAuth listener. Proposal digests bind exact bytes but are not signatures,
human consent, one-use tokens or evidence of real bank approval.

## Verification and remaining integration

Focused public tests exercise exact finance and trend behavior, fixture/source
binding, canonical scope mutation, actual official SDK modern and legacy stdio
clients, denied authority claims, strict arguments, fixed no-echo errors,
malformed/oversized/ambiguous/deep JSON input, negotiation-error redaction,
recovery after denial, late-result denial and ready-confirmed child termination.
A test-only awaitable gate exercises actual modern and legacy stdio cancellation,
busy denial and admission recovery before the unchanged two-second deadline.
The gate and its fixed admission notification are absent from production launch.
Report-brief tests cover all17 source mappings and unchanged aggregate golds,
scope/source denial, per-response isolation and actual modern/legacy frame caps.
Tests use fictional values and no bank/model network calls. Dependency
checks, formatting and the focused suite also run in an isolated CI environment.
The complete local suite passed57 methods. A fresh official-SDK walkthrough
passed75 calls across all four personas, including17 reports,17 proposals,
20 guidance entries, three trends, five calculators and six denials. The
[synthetic receipt](evidence/bank-mcp/stdio-walkthrough-20261117.json),
[byte-identical publication provenance](evidence/bank-mcp/publication-provenance.json),
[retained suite output](evidence/bank-mcp/suite-20261117.json)
and [local observation](evidence/bank-mcp/local-qualification-observation.json)
state their exact scope. These are synthetic source checks, not production or
bank qualification; current exact-head and separate main CI remain required.

This initial coherent adapter reads the immutable in-memory fixture. The chosen
future persistence direction is one separate analytical PostgreSQL/pgvector
service alongside Aqua's existing private application PostgreSQL. A PG adapter
must preserve these source, scope, report-ID and budget contracts and pass its
own integration checks before activation. It does not require another vector,
document or broker database. This demo creates or migrates no database.

Real bank rollout still needs a bank-approved identity/authorization adapter,
approved source ingestion and freshness, explicit data minimization, durable
human review and audited execution controls, operational recovery and capacity
qualification, and applicable bank security/legal review. None is established by
synthetic demonstrations, MCP connectivity, annotations, passing unit tests or
the ability to calculate a ratio. No training-packet approval is implied.
