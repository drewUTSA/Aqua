# Aqua sales demo · one presenter and two viewers

**14 minutes, three devices.** Count transactions, trace a chart to its saved rows, correct a private note and prepare a fictional month-end review. Screen-share the presenter's window. Each viewer uses their own account and history.

### Before the call

| Seat | Set up and rehearse |
| --- | --- |
| Presenter · desktop | Use a synthetic account with a current dataset grant. Rehearse the two prompts below and reopen the correct saved answers. Check **Show visuals**, **Chart**, **Table** and **Understand this result**. Open a separate analyst MCP host. |
| Viewer A · laptop | Sign in with a different granted synthetic account. Have one recent chat or answer ready in its own history. |
| Viewer B · phone or tablet | Use a third synthetic account without an analytical grant. Sign-in, settings and Privacy are available. |

The web segment requires a **prepared private HTTPS demo origin** reachable by all three devices, schema 10 app storage, synthetic sign-ins and a separate read-only analytical connection. The sales database contains 1,000 fictional transaction amounts from 1 through 1,000 CZK dated November 1–16, 1996. The MCP’s fictional USD reports use a separate bundled snapshot dated November 16, 2026. [Sales database](../../db/sales_demo/bootstrap.sql) · [Private app storage](../../ops/appdb/README.md)

From the repository root, use PostgreSQL's client tools with an administrator who can create databases and roles on a **new, dedicated PostgreSQL demo cluster**. It must contain only the standard databases. Keep its listener private. Configure a `hostssl` rule for `aqua_sales_demo_reader`, database `aqua_sales_demo`, the backend’s private address and `scram-sha-256`. Reject the reader’s other connections before broader rules. Use a direct libpq connection or a service profile that enforces the same certificate and hostname checks.

```powershell
$env:PGHOST = Read-Host 'Private demo database DNS name on its TLS certificate'
$env:PGUSER = Read-Host 'Demo database administrator login'
$env:PGSSLMODE = 'verify-full'
$env:PGSSLROOTCERT = (Resolve-Path -ErrorAction Stop -LiteralPath (Read-Host 'Path to the trusted demo CA certificate')).Path
psql -X --dbname=postgres --file=db/sales_demo/create_database.sql
if ($LASTEXITCODE -ne 0) { throw 'Could not create a fresh sales demo database' }
psql -X --dbname=aqua_sales_demo --file=db/sales_demo/bootstrap.sql
if ($LASTEXITCODE -ne 0) { throw 'Sales demo bootstrap failed' }
psql -X --set=ON_ERROR_STOP=1 --dbname=aqua_sales_demo --command "SET password_encryption='scram-sha-256'" --command '\password aqua_sales_demo_reader'
```

The first script checks the maintenance database read-only before creation. Reserve the cluster until setup completes. A concurrent cluster change can cause the second script to stop with the newly created database still empty. Enter a new demo-reader password at the private prompt.

From the permitted backend address, use the same private DNS name, trusted CA and `verify-full` settings. Run `psql -X --username=aqua_sales_demo_reader --dbname=aqua_sales_demo --password --file=db/sales_demo/check_reader.sql` to verify the reader and both presenter answers. Configure the demo backend's `DATABASE_URL` through its secret configuration with the same reader, database, DNS name and explicit `sslmode=verify-full` and `sslrootcert` parameters. Give the backend a readable copy of that trusted CA at the specified path. Keep `APP_DATABASE_URL` pointed at the separate schema 10 application store. Provision the presenter’s current dataset grant for this connection. Rehearse the chart and save it in the presenter’s account before the call.

On November 19, one signed-in presenter used a different 66-row fictional ledger. Aqua returned 8/8 correct saved answers within 45 seconds, with one model call per question. Times ranged from 7.61 to 43.91 seconds. The two preselected repeat questions, covering leap day and tied rankings, both returned the same correct results. The three-person demonstration was measured separately. [Three-person results](P12_PROGRESS.md#three-person-demo-acceptance)

On the **demo** backend, enable `COMPANION_ENABLED=true`, `CONTEXT_NOTES_ENABLED=true`, `BANK_DEMO_ENABLED=true` and `BANK_DEMO_PERSONA=analyst`. Select the approved local Ollama endpoint and installed model with `LLM_PROVIDER=ollama`, `LLM_FALLBACK=off`. The web report persona applies to the whole instance. Analytics grants, chats and notes remain account-specific. [Companion configuration](RESULT_COMPANION_CONTRACT.md) · [Notes configuration](CONTEXT_NOTES_CONTRACT.md) · [Web report scope](BANK_DEMO_WEB_CONTRACT.md)

Build from `frontend/` with `VITE_AQUA_DEMO_MODE=false` and `VITE_AQUA_USE_MOCK=false` using `npm ci --ignore-scripts --no-fund` then `npm run build -- --manifest`. Serve the frontend and authenticated `/api` at the prepared origin. [Frontend build](../../frontend/scripts/build.mjs)

For local MCP, run these PowerShell commands once from the checkout root. Set that directory as the MCP host's working directory and select the environment's Python executable. [SDK setup and launcher](BANK_MCP_DEMO.md)

```powershell
py -3.12 -m venv .venv-bank-demo
.venv-bank-demo/Scripts/python.exe -m pip install --require-hashes -r tools/bank_demo/requirements-bootstrap.txt
.venv-bank-demo/Scripts/python.exe -m pip install --require-hashes -r tools/bank_demo/requirements-lock.txt
.venv-bank-demo/Scripts/python.exe -m pip check
```

Pass `-B -m mcp_demo --persona analyst` as host arguments. An optional second stdio process with `--persona teller` sees only deposits and service cases. The analyst sees reconciliation, liquidity, credit review and commercial exposure. The host selects each persona at launch. Use the host's tool interface for the calls below.

### What to do on screen

| Elapsed | Person and surface | Action and evidence to show |
| --- | --- | --- |
| 0–2 min | All three · browser | Open `/signin` at the private demo origin and enter each person's own credentials off screen. The signed-in workspace is `/`. Viewer A opens their own recent item. Viewer B opens `/settings`, then `/privacy`. The presenter shares the application window after signing in. |
| 2–4 min | Presenter · workspace | In a new chat, send **“How many transaction records have an amount strictly greater than 997? Return the count.”** The fixture reference is **3**. Open **SQL** to show the comparison. If the answer is late or wrong, keep its original outcome and use the saved-answer fallback below. |
| 4–6 min | Presenter · workspace | Open the presenter's previously rehearsed chart. Its prompt is **“Show a bar chart of transaction counts by amount band. Call amounts of 250 or less ‘250 or less’ and amounts above 250 ‘above 250’. Return amount_band and transaction_count, ordered by transaction_count descending.”** Check **Show visuals → Chart → Table**. The reference rows are **above 250 = 750** and **250 or less = 250**. Open **Result details**, **SQL** and **Understand this result → Returned field to inspect → transaction_count**. Quote what the screen shows: **“Among these two returned rows, the highest count is 750, saved row 1, field 2.”** Check the returned ordering and field position before quoting. Distinguish generation time from source freshness when the latter is unavailable. |
| 6–8 min | Presenter · workspace | Open **Help** (accessible name **Open Aqua tools**) → **Saved notes → New saved note**. Use label **Demo bands** and body **Use 250 as the inclusive lower-band ceiling.** Choose **Save note**. Reopen it, append **Report counts only.**, and choose **Save correction → Prepare for composer**. Edit the preview to **Show transaction counts for the two saved amount bands.** Choose **Apply to composer draft** and leave it unsent. Reopen the note and choose **Forget this entry… → Forget saved entry**. Check it has left this account's library. A copy previously sent would still belong to its chat history. |
| 8–10 min | Presenter · workspace | Return to **Help → Fictional bank demo**. Pick the reconciliation report, then **Read fictional report**. Read the table definition and open **Cited fictional procedure and human next steps**. For **November 1–16, 2026**, the **Central** branch's statement closing exceeds its calculated ledger closing by **USD 250.00**. The other two fictional branches show zero difference. Point to the partial-period notice and procedure citation. |
| 10–13 min | Presenter · local MCP host | Switch windows and use the analyst tool card below. Retrieve the cited procedure, inspect the operating-surplus history, calculate the September-to-October change and prepare the review draft. Invite Viewer A to read the period and Viewer B to identify who must decide whether to act. |
| 13–14 min | All three | Ask each viewer to name the source of one number and the next human decision. Record device, browser, task, time and whether help was needed. Sign out of each web session and close the local MCP host processes. [Fictional data definitions](BANK_DEMO_DATA.md) |

### Rank groups in a new chat

Sign in as the granted presenter, open an empty new chat and expand **Rank groups**. On the fictional sales database, enter `trans` under **Source** and `account_id` under **Group by**. Choose **Count records**, **Highest first**, **1**, and **Include ties at the cutoff**. Select **Use this draft**, review it, then press **Send**. Accounts 1 and 2 each have 500 transactions, so both belong in the answer. Selecting **Exactly this many groups** in a new chat returns a single group with the stable tie-breaker.

For **This many distinct scores**, employees choose how many different count or total values to include. For example, group totals of 12, 12, 9 and 7 produce three groups at the two highest distinct scores. Results cover groups represented in the source. The form is available on both interfaces to a signed-in employee with query access. [Ranking behavior](P12_PROGRESS.md#employee-selected-group-rankings)

### Presenter's MCP tool card

Ask **“What was the Central difference, how did operating surplus change, and what needs human review?”** Use the following tools in the **analyst** process. The cause of the difference remains for a reviewer to investigate.

| Tool | Input or values to copy |
| --- | --- |
| `demo_context`, then `list_authorized_reports` | Use `{}` for each. Confirm the analyst persona and the presence of `reconciliation_summary`. |
| `run_demo_report` | `{"report_id":"reconciliation_summary"}`. Keep the returned `data.source_revision` for the final call. Confirm Central's `difference_usd` and the report period. |
| `search_demo_guidance` | `{"query":"How should finance review a fictional ledger reconciliation?","limit":1}`. Open the returned `finance_help` citation. Read the definition of statement minus calculated closing. The procedure belongs to Aqua's fictional demo. |
| `analyze_monthly_trend` | `{"metric_id":"gl_operating_surplus"}`. Show the complete historical months and excluded partial November. This describes a generated ledger series. It supplies neither a forecast nor a causal explanation of Central's difference. |
| `calculate_finance` | Take the two values from the trend response. For this snapshot, use `{"operation":"percent_change","parameters":{"currency":"USD","period":"month","previous_usd":"141000.00","current_usd":"149000.00"}}`. September to October rose **USD 8,000.00**, or **5.673759%**. |
| `prepare_review_proposal` | Use the object below. Insert the revision returned by the report. Read `status=proposal_only`, `requires_human_approval=true`, `approval_recorded=false` and `execution_enabled=false`. A person can review and decide through their own workflow. |

```json
{
  "report_id": "reconciliation_summary",
  "expected_source_revision": "<paste data.source_revision from this report>",
  "action_id": "draft_internal_followup",
  "note": "Review the Central branch USD 250.00 statement-minus-ledger difference before month-end."
}
```

### If a query takes too long

At 45 seconds, say **“We haven’t received a verified answer within our target. I’ll show the answer I saved during rehearsal.”** Record late and incorrect results as observed. Reopen the presenter's own verified answer. If the chart is unavailable, show the exact table and mark the chart as unshown. Record any blocked sign-in, grant or provider. The MCP portion can proceed independently.

### Keep the performance score separate

The **90% within 45 seconds** criterion covers fresh live analytics. Exclude rehearsals, saved answers, MCP calls and viewer reads. The separate 178-row workload uses **three independently authorized synthetic accounts**: one submitting presenter and two viewers reading their own account state. This walkthrough deliberately gives Viewer B no analytical grant.

The November 18 PR 93 application met the target on that workload. It saved 19/20 answers within 45 seconds, including 18/20 correct answers. Together the two viewers completed all 489 reads of their own data. A ranking omitted a tied winner and one calendar request timed out. The separate 178-row scored fixture and test harness are operator-held. The 1,000-transaction fixture linked above supports this walkthrough from the checkout. [Full results, earlier studies and timings](P12_PROGRESS.md#three-person-demo-acceptance)

For a new measurement, freeze 20 fresh questions and expected results. Time from submission through the presenter's read of the completed saved answer in its job and history. At least **18 of 20** must be correct within 45 seconds. Keep errors, wrong, late and unobserved tasks in the denominator. Report timely delivery, accuracy and P50/P90/P95 separately. Human sign-off requires the three intended devices, authorized origin and actual participant observations.

### Restore a synthetic sales database

For a private copy of the fictional sales ledger, run `pg_dump --format=custom --create --file=sales.dump --dbname=aqua_sales_demo` as the demo administrator. Use the private TLS settings from setup. Record the file’s SHA-256 separately and compare it before restoring. The dump includes the sales database’s table grants and database-specific role settings. The analytical login itself belongs to the cluster.

Prepare a new, empty, dedicated demo cluster. Switch the administrator connection to that cluster and confirm its hostname, trusted CA and maintenance database. Create the login with `CREATE ROLE aqua_sales_demo_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS`. Restore with `pg_restore --exit-on-error --create --dbname=postgres sales.dump`. If restoration stops partway, use a fresh demo cluster for the next attempt. Set a fresh reader password at the private prompt, configure its `hostssl` rule, and run the reader check from the permitted backend address. The expected presenter counts are 3, 750 and 250. Application accounts, chats and notes have their own backup in the separate app database.
