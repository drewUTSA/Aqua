# Bank demo web contract — first reports increment

Version1, optional and default off. Two authenticated private JSON routes expose
the original fictional report truth through a least-data web projection. No
model, SQL, new database, stored conversation, proposal/approval or executor.
`BANK_DEMO_ENABLED=false` and `BANK_DEMO_PERSONA=none` are the defaults. The host
alone selects `none|teller|analyst|manager`; request roles/tenants/personas cannot
change it. App `owner_id` is the authenticated Aqua account, separate from the
immutable synthetic DemoActor. Analytical `bank` grants confer no demo role.

| Host persona | Context / picker | Report reads |
|---|---|---|
| none | Fictional notice, empty picker | Denied |
| teller | Branch/deposits + customer service | Those two only |
| analyst | Finance/accounting, treasury, credit, commercial lending | Those four only |
| manager | All17 fictional departments | All17 aggregate reports |

`GET /api/v1/bank-demo/context` has no query parameters. Success is exactly
`{schemaVersion:1,owner_id:UUID,context:Context,reports:ReportOption[]}`.
`POST /api/v1/bank-demo/reports` requires same-origin cookie + Origin/CSRF and
exactly the following JSON, capped at8192 raw bytes; duplicate/escaped duplicate
keys, unknown fields, bool-as-version and wrong types are rejected:

```json
{"schemaVersion":1,"report_id":"deposit_portfolio_summary","expected_source_revision":"8c27aa965ae4087fc965f66957ab08dde9b18de1cf6abdd321102afb6f8cdd37"}
```

Success is exactly `{schemaVersion:1,owner_id:UUID,result:Report}`. Server fixes
November1–16,2026 / USD; no caller period, currency, rows, source, SQL or URL.
All DTO keys below are required, closed and case-sensitive:

```typescript
type Context = {
  bankName:string; persona:"none"|"teller"|"analyst"|"manager";
  asOf:"2026-11-16"; sourceRevision:Hex64; guidanceRevision:Hex64;
  notice:string; scopeSource:"fixed_fictional_demo_registry_not_bank_identity";
  synthetic:true; demoOnly:true; jurisdiction:"US"; currency:"USD";
  executionEnabled:false; approvalRecorded:false;
};
type ReportOption = { id:ReportId; label:string; department:DepartmentId };
type Report = {
  reportId:ReportId; title:string; department:DepartmentId;
  asOf:"2026-11-16"; sourceRevision:Hex64; guidanceRevision:Hex64;
  period:"2026-11"; periodStart:"2026-11-01"; periodEnd:"2026-11-16";
  periodComplete:false; truncated:false; currency:"USD"; jurisdiction:"US";
  synthetic:true; demoOnly:true; readOnly:true;
  executionEnabled:false; approvalRecorded:false;
  definition:string; caveats:string[];
  columns:{key:string;label:string;unit:"text"|"count"|"USD"}[];
  rows:string[][]; rowCount:number;
  procedure:{title:string;text:string;sourceId:string;version:string;
             contentSha256:Hex64;fictional:true};
  nextSteps:{id:string;text:string}[];
};
```

Column metadata is server-owned and explicitly mapped from the canonical report
schema. Cells preserve source order and exact text: counts become base10 integer
strings, USD values remain the original two-decimal strings (including sign),
and text remains text. The browser never infers units or converts money through
float. There are1–12 rows, at most8 columns, exactly3 canonical caveats and3
inert next steps. The procedure text/citation and all metric definitions come
from the existing original report/brief, not browser logic or model generation.
Each report title equals its corresponding picker label. UTF8 transport is
required; BOM, UTF16/32 and embedded NUL payloads are rejected.
No unused monthly series, scope fingerprints, raw records or MCP metadata enters
the web DTO. The complete outer response is capped at32768 UTF8 bytes.

Example `none` context: `reports:[]`, `context.persona:"none"`, the source revision
above and a conspicuous fictional/non-connected notice. A teller gets exactly
`deposit_portfolio_summary` and `service_case_summary`. Example deposit columns
are `branch/Branch/text`, `product/Product/text`, `accounts/Accounts/count`,
`closing_balance_usd/Closing balance/USD`; its first row is exactly
`["north","checking","1200","1461250.00"]` and all seven source rows are returned.

Each request spends existing durable workspace admission, freshly checks the
session/account/history in a short transaction with `guard(data=False)`, and
rechecks before publishing within a two-second cooperative deadline. Responses
are no-store/private; frontend must bind owner + revisions, discard late/closed/
account-changed responses, and never retry or write to the composer implicitly.
Errors use the existing fixed `{error:{code,message,request_id}}` envelope:
disabled404 `not_found`; missing/revoked auth401 `session_invalid`; forbidden
report403 `access_denied`; invalid/duplicate/query input422 `invalid_request`;
wrong media415; oversize413; changed source409 `revision_conflict` (reload
context); admission429 `rate_limited`; deadline/source failure503
`service_unavailable`. Error bodies never echo input or exception text.

Runtime packaging is explicitly limited to the7 pure `eval/banking` modules,
empty `eval/__init__.py`, `mcp_demo/{__init__,data,protocol,reports,guidance,web}.py`
and `mcp_demo/fixtures/bank.json`; no SDK/server/evaluation runner/training data.
Existing MCP DTOs/golds and the10-module application-help package stay intact.

The immutable host-created `SyntheticReportSource.context/report` producer is
separate from app identity, HTTP, admission and response budgets. There is no
caller-selected source, real-data flag, DSN or URL. A future approved connector
and identity/entitlement adapter can supply a separately reviewed producer and
compatible bounded presentation fields; the current fictional DemoActor and
`demoOnly` promises must never be reused as real-bank authorization.

## Local qualification and activation boundary

The reports increment has passed the full isolated backend matrix, both-shell
mocked-HTTP browser journeys and actual isolated nginx checks. The current
runtime inventory explicitly contains226 Python/SQL files,230 app files and one
runtime lock. See [qualification](BANK_DEMO_WEB_QUALIFICATION_20261117.md) for
the source bindings, failed-attempt dispositions and remaining limitations.

To opt into a local demonstration, the operator must pass
`BANK_DEMO_ENABLED=true` and one fixed `BANK_DEMO_PERSONA` in the backend process
environment. The existing frontend is built with real-auth/mock flags disabled;
the report UI uses the authenticated API. No production configuration was
changed by qualification. A process-level flag does not configure a bank
connection or confer real-bank entitlements.
