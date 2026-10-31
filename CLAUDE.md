# Aqua project guide

Instructions for coding agents working in this repository. Read this file before making changes.

Latest verified checkpoint: P00 through P10 are complete and deployed at
`d242d2ee1b4a91e2a7ffa1d2ed2568d87e63da09` (PR #56, `Phase10 Identity`),
private schema 7. The 2026-10-31T04:08:14 UTC release passed after all five
PR/main CI jobs, fresh stopped-writer encrypted backup and owner-only 30-day
retention. Protected rows, environment, volumes and mail schedule were preserved;
live GET-only sign-in smoke passed and its screenshot was reviewed. See
`docs/implementation/evidence/p10c/release.json`. P11 is the current phase;
exports and deletion are not deployed. The earlier slices below are historical.
The simplified homepage merged as `7c0caae8ac0d5fa1c74866bd898d317c1fc984ea`
(PR #53, `Phase9 Homepage`). Both required CI runs passed all 29 steps. The
October 28 23:10:19 UTC frontend-only release preserved the exact P09 backend,
schema 5, private volumes/environment, authentication, mail worker and scheduler.
All origin/public asset hashes and private API denials passed; the bounded
public sign-in browser passed. See `docs/implementation/evidence/homepage/release.json`.

P10a adds display-name editing and explicit read-only methods/session reviews,
separate from preference saves. The candidate passed 1,440 backend cases,
455 frontend units, both builds and ten browser gates (568 checks), with all
234 frontend inputs/nine assets bound and 26 screenshots reviewed. Runtime
audits, actual synthetic restore, storage/proxy checks and resource cleanup
passed. Required PR/main CI passed and P10a was deployed at 2026-10-28T23:42:41.253826+00:00
on private schema 6 after a fresh authenticated encrypted backup. Migration
0006 preserved protected rows, environment, volumes and the mail scheduler.
Main is `f5f5b2d16fab261173fd2572e620f266dc64168e` (PR #54, `Phase10 Accounts`).
See `docs/implementation/evidence/p10a/release.json` for exact release evidence.

P10b security is now deployed from PR55/main `7477e28` at
2026-10-31T01:50:04.383058+00:00, still schema 6. All 1,519 backend cases,
492 frontend units, 22 browser gates and 62 root-reviewed screenshots passed;
both PR/main runs passed all three jobs. The cutover preserved protected state,
environment, volumes and scheduler; public sign-in smoke passed. See
`docs/implementation/evidence/p10b/release.json`. The following P10a API
description is historical slice scope.

P10c identity passed 1,635 backend cases, 528 frontend units and all 42 browser
gates; root reviewed all 104 selected screenshots. Schema-compatible recovery,
migration rehearsal, PR/main CI and the backup-gated release passed. See
`docs/implementation/evidence/p10c/verification.json` and `docs/implementation/P10_PROGRESS.md`.
P11a
exports are isolated preparation; P11 deletion and P12–P13 remain incomplete.
No public Google audience or analytical grant changes are authorized.

### P10a account API (historical foundation slice)

`GET/PATCH /api/v1/me` expose the current verified app profile and display-name
revision. PATCH accepts only `{expectedRevision, display_name}`, enforces
Origin/CSRF and owner-scoped CAS; a conflict returns 409. Name normalization
is NFC, single-line, 1–120 code points and at most 512 UTF-8 bytes, without
control/format characters. Google sign-in no longer overwrites the app profile
or primary email. `GET /api/v1/me/methods` and `GET /api/v1/me/sessions` are
bounded read-only owner views without analytical grants or idle extension.
Only profile-edit/method-list/session-list capabilities are available. No
public proof issuer, password/email/link/revocation operation is enabled here.
Private migration 0006 is additive; applied 0001–0005 are immutable. Code on
schema 6 needs compatible forward recovery or maintenance, never a P09 image
rollback. See `docs/implementation/P10A_ACCOUNT_FOUNDATION.md`.

The user explicitly authorized direct server access and routine server updates
after required checks pass. A dedicated key-backed Windows SSH alias,
`aqua-codex`, has been verified; use the user's SSH config, never copy private
key contents into the repository. Preserve phase isolation and recovery gates.
The user also explicitly authorized the specific P05 test/CI/docs repair on
October 26: commit it on a separate branch, publish its PR, and merge only after
required GitHub checks pass. The October 28 user instruction supersedes that earlier narrow Git exception; the current Git authorization below covers the remaining phases.

### P09 preference API (deployed)

`GET /api/v1/me/preferences` returns `{schemaVersion:1, revision, values,
capabilities}` for the current authenticated account, including accounts without
a dataset grant. `PUT` accepts only `{schemaVersion:1, expectedRevision, values}`
with a complete allowlisted account snapshot and ordinary Origin/CSRF defenses.
An atomic revision mismatch returns 409. Unknown/newer stored settings are
preserved and block overwriting; the client requires an explicit reload/review.
Reads and writes share the durable 60/account/minute workspace budget. Device
preferences have separate bounded owner-scoped storage, never a server-sync claim.
Imports are versioned data only, at most 64 KiB; permissions, consent, secrets,
custom instructions and destructive operations cannot enter preferences. Schema
5 was reused without a preference migration; the current app schema is 6.
P10 account editing, sensitive security actions and identity operations are
deployed. P11 privacy jobs remain unavailable in production.

## What this project is

A natural-language-to-SQL app. A user asks a question in plain English and gets back the result rows, a short readable summary, and the exact SQL that produced them.

UTSA Senior Design capstone, Fall 2026 to Spring 2027. Professor: John Heaps. Budget is $0, so every dependency must be free tier or open source.

The research contribution is the retrieval layer (what context the model sees) and the validation layer (proving generated SQL is safe before it runs). The LLM call itself is one small function. Fine-tuning an open model and comparing it against Gemini is a later phase.

## Team

| Person | Owns |
|---|---|
| Andrew Velazquez | Database and table setup (`db/`), backend |
| Audie Ploe | Tableau dashboards, backend |
| Benjamin Spear | Domain and hosting, frontend (`frontend/`) |

## Where the code lives

- GitHub repo: `drewUTSA/Aqua`
- Ubuntu server checkout: `/srv/bank-ai` (the docker-compose project is also named `bank-ai`)
- Public site: `aqua-ai.us`, served by the frontend container on port 5173
- Local development: each person's own clone

The server runs the app with docker-compose. Code changes are made locally, reviewed through a pull request, merged after required checks pass, and pulled on the server. The October 28 instruction authorizes Codex to handle these Git steps. Nobody commits on the server: its GitHub key can only pull.

## Current stack

| Concern | Choice |
|---|---|
| Backend language | Python 3.12 (not 3.14; the ML stack does not fully support 3.14 yet) |
| API | FastAPI on 127.0.0.1:8000; public hostnames enter nginx on 127.0.0.1:5173. P10a checkpoint `f5f5b2d` (PR #54) is deployed with schema 6 and verified public delivery |
| Sign-in | Canonical UUID accounts with revocable digest-only sessions, Google and password sign-in. Password login/registration/recovery and branded mail are active; the scheduler runs a separate worker and the web worker flag stays false |
| Frontend | React 19 with Vite. Production: a static build served by nginx on port 5173, which forwards `/api` to the backend and rate-limits questions. Development: `npm run dev` forwards API calls but is not the production rate-limit boundary |
| Analytical database | PostgreSQL on Tiger Cloud free service (TimescaleDB, pgvector, pgvectorscale); unchanged in P02 |
| Application database | Private PostgreSQL 17 is active at schema 6, socket only, network none and separate roles. Applied migrations 0001–0006 are immutable |
| Sample data | Pagila (Postgres port of Sakila) |
| LLM | Gemini API with the free `gemini-3.5-flash-lite` by default (`LLM_PROVIDER=gemini`). When it is out of quota or down: Ollama (`qwen3`) on Ben's server over Tailscale, then `gemma-4-26b-a4b-it`. Model names read from env |
| Embeddings | `gemini-embedding-2` at 768 dimensions, stored in pgvector in the `retrieval` schema (Phase 4) |
| SQL parsing and validation | `sqlglot`, Postgres dialect |
| DB driver | `psycopg` 3; separate bounded `psycopg_pool` for opt-in application storage |
| Dashboards | Tableau, connected to Tiger Cloud with a read-only role |
| Tests | pytest |
| Formatting | black, default settings (ruff for linting) |
| Deployment | docker-compose on the Ubuntu server, `network_mode: host`; HTTPS is handled in front of nginx |
| Fine-tuning (later) | Open model such as Gemma with Unsloth LoRA, served by Ollama or vLLM |

Gemini cannot be fine-tuned through the free API, which is why fine-tuning targets an open model.

### Model choice

No model name is hardcoded. `LLM_PROVIDER` picks the server default (`gemini` or `ollama`), and `GEMINI_MODEL`, `OLLAMA_MODEL` and `GEMINI_EMBED_MODEL` come from `.env`, so switching models is a config change, not a code change. The default is `gemini-3.5-flash-lite` through the Gemini API: free, about one second per answer, and the most accurate model in our eval (`docs/decisions.md`). When it is out of quota or down, the question goes to Ollama, then to `GEMINI_FALLBACK_MODELS` (default `gemma-4-26b-a4b-it`, free with its own quota). Gemma 4 thinks before answering, which costs 15 to 90 seconds, so it is the fallback, not the default. Ollama stays for the fine-tuned model later. The UI can pick either per question (`GET /api/models`). Keep every model out of pytest. Record each model change and its eval result in `docs/decisions.md`.

### Providers

Both providers sit behind the same `complete()` call in `nl2sql/llm.py`, so the rest of the pipeline does not change when the provider does.

- Gemini API: Gemini models get the rules as a system instruction and a JSON schema for `{"sql": ...}`. Gemma models take neither, so for them the rules go at the top of the prompt and `generate.extract_sql` reads the SQL from the code fence Gemma writes. P07 provider attempts, fallback, embedding and SQL repair share a four-call budget and one 120-second job deadline; SDK automatic retries are disabled. Each provider slice is bounded by the remaining deadline. If a model still fails with an outage, a spent quota or a timeout, and `LLM_FALLBACK` is on (the default), `complete()` follows `llm.fallback_chain()`: Gemini Flash-Lite, then Ollama, then each of `GEMINI_FALLBACK_MODELS` (when Ollama is chosen, Ollama first, then the Gemini models). Any Ollama failure moves on, because Ben's machine may simply be off. An empty Gemini reply (a safety or recitation stop) also moves on. Bad keys and model names (400, 403, 404) never fall back, so configuration mistakes stay visible. The answer reports the model that actually answered.
- Ollama: called with a JSON schema, Qwen's recommended sampling, a fixed seed and a 16k context. `OLLAMA_THINK` turns reasoning on or off; on was more accurate in testing.

## Repository layout

```
aqua/                         (checked out at /srv/bank-ai on the server)
├── CLAUDE.md                 This file
├── README.md                 Human setup guide
├── .env.example              Variable names only, no real values
├── .gitignore
├── docker-compose.yml        backend + frontend services
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt      Runtime dependencies, including google-genai for retrieval
│   ├── requirements-ml.txt   Later: fine-tuning stack only
│   ├── main.py               FastAPI routes only; calls nl2sql.pipeline
│   ├── nl2sql/
│   │   ├── __init__.py
│   │   ├── config.py         Loads env, exposes typed settings
│   │   ├── db.py             Connection as the read-only role
│   │   ├── schema.py         Reads tables, columns, keys from the database; prompt text, allowlist, table docs
│   │   ├── llm.py            Thin model wrapper; the only file that calls a model (Gemini API, Ollama)
│   │   ├── generate.py       Builds the prompt (schema, examples, failed attempt) and asks for SQL
│   │   ├── validate.py       AST safety checks (layer 1)
│   │   ├── execute.py        Runs validated SQL in a read-only transaction
│   │   ├── summarize.py      Turns result rows into a short answer, by rule, no model call
│   │   ├── visualize.py      Picks a chart for a result (first version; Ben owns it)
│   │   ├── response.py       Answer -> the JSON the frontend renders
│   │   ├── answer_size.py    How many rows a question asks for: a number, top 10, ties, per group
│   │   ├── cache.py          Reuses recent successful answers to the same question and model
│   │   ├── pipeline.py       context -> generate -> validate -> execute, one retry if fixable
│   │   ├── retrieval/        Phase 4: embed.py (Gemini), store.py (offline indexer), select.py
│   │   └── querylog.py       Phase 7, not built yet: logs questions, SQL, outcome
│   └── tests/
│       ├── test_validate.py  Highest priority; adversarial SQL cases
│       ├── test_db_readonly.py Confirms writes and hidden columns fail as nl2sql_reader
│       └── test_pipeline.py  Pipeline with the LLM mocked
├── frontend/
│   ├── Dockerfile            Builds the site, then serves it with nginx
│   ├── nginx.conf            Static site, /api proxy, rate limit, security headers
│   ├── package.json          npm run dev | build | test
│   ├── vite.config.js        Dev server; proxies /api to 127.0.0.1:8000
│   ├── checks/               node --test suites (npm test)
│   ├── index.html
│   └── src/
│       ├── services/aquaClient.js  The only API entry point components use
│       ├── services/apiClient.js   Real transport: /api/query, /api/models, error mapping
│       └── services/mockClient.js  Offline stand-in, on with VITE_AQUA_DEMO_MODE=true
├── db/
│   ├── README.md             How to rebuild the database from scratch
│   ├── 01_extensions.sql     vector, vectorscale
│   ├── 02_load_pagila.sh     Loads Pagila, strips OWNER TO lines
│   ├── 03_users.sql          Creates nl2sql_reader (psql prompts for the password)
│   ├── 04_retrieval.sql      retrieval schema, embedding tables, nl2sql_indexer role (Phase 4)
│   └── 05_hide_columns.sql   Takes staff.password and staff.picture from the reader (Phase 5)
├── eval/
│   ├── datasets/             pagila_v1.jsonl: 50 test and 25 train questions with gold SQL;
│   │                         pagila_size_v1.jsonl: 17 questions testing answer size rules
│   ├── run_eval.py           Runs the pipeline over a dataset; --retrieval, --model, --fallback, --ids, --check-gold
│   ├── metrics.py            Execution accuracy, validity rate, latency
│   └── results/              Gitignored output
├── finetune/                 Later: data prep and training scripts
└── docs/
    ├── architecture.md       How a question becomes an answer, the safety layers, deployment
    └── decisions.md          Every significant choice and why
```

Directories that only hold a `.gitkeep` are placeholders. `backend/Dockerfile` copies `main.py`, `auth/` (Google verification, sessions and access checks), the whole `nl2sql/` package, `storage/` and versioned migrations; `eval/` and `db/` stay out of the image. Production and CI use the same hashed dependency lock with a repository-root build context.

P06/P07 additionally include `workspace/` and `analysis/` in that runtime image.

## API contract

The frontend talks to the backend only through `/api`, which in production goes through nginx. Keep these shapes stable; change them only with Ben's agreement. `frontend/src/services/apiClient.js` is the one place the frontend reads these shapes.

| Route | Purpose |
|---|---|
| `GET /api/health` | Liveness for the Docker healthcheck: `status`, `database_configured`, `model`, `retrieval`. Never touches the database or model |
| `GET /api/ready` | Internal loopback readiness; reports storage disabled or required schema version 5, fixed 503 on failure. Public nginx denies this route and normalized aliases |
| `GET /api/auth/config` | Returns `client_id`, `nonce`, `csrf_token`, boolean `capabilities`; persists a single-use challenge and sets its opaque cookie |
| `POST /api/auth/google` | Body `{"credential": str}` plus `X-CSRF-Token` from config and matching `Origin`. Verifies Google's token and nonce, sets the Aqua session, returns canonical `user.id`, safe profile, `csrf_token`, `can_query`, and `capabilities` |
| `GET /api/auth/me` | Requires an Aqua session; returns canonical `user.id`, safe profile, `csrf_token`, `can_query`, and `capabilities` |
| `POST /api/auth/logout` | Requires session, matching `Origin`, and session `X-CSRF-Token`; commits durable revocation, then clears the cookie and returns 204; failed revocation returns 503 and preserves the cookie |
| `GET /api/models` | `{"models": [{"id", "name", "description"}]}`, server default first. Lists `gemini` only when `GEMINI_API_KEY` is set |
| `POST /api/query` | Requires session, matching `Origin`, session `X-CSRF-Token`, and an approved account. Body `{"question": str, "model": "ollama" or "gemini" (optional)}`. Returns `{"status": "success" or "error", "sql": str, "model": str, "message": str, "tables": [...], "visualizations": [...], "kpis": [...], "error": {"code": str, "message": str, "retryable": bool} or null}` |
| `POST /api/v1/chats/{chat_id}/messages` | Saves owned canonical input/request and returns 202 lifecycle snapshot; request-key replay never starts another job |
| `GET /api/v1/analysis-requests/{id}` | Current authorized lifecycle snapshot; terminal result requires current ownership/grant |
| `POST /api/v1/analysis-requests/{id}/cancel` | Same-origin session/CSRF plus strict empty JSON body; server cancellation, independent of browser abort |
| `GET /api/v1/analysis-requests/{id}/events` | Bounded metadata-only SSE with current-authority revalidation and owned-status polling fallback |

The shape matches what the React app renders, plus `sql` so every answer shows its query. Each table is `{"id", "title", "columns": [{"key", "label", "type"}], "rows": [{key: value}]}`, where `type` is `string`, `number`, `currency`, `percentage` or `date`; dates are ISO strings. A rejected or failed query returns HTTP 200 with `status` "error", the SQL the model wrote, and the reason, so the UI can show what was blocked. An unreachable model or database returns 503 with `retryable` true; a blank or over-long question returns 422. An unknown `model` is also a 422. Choosing `gemini` on a server with no key returns 400 with code `model_not_configured` and `retryable` false. `message` is a rule-based summary from `summarize.py`. `visualizations` and `kpis` come from `visualize.py`: a single number gives one KPI (`{"id", "label", "value", "type"}`) plus a `{"type": "kpi"}` visualization; labels with a measure give a `bar`, a date with a measure a `line`, each `{"id", "type", "title", "tableId": "result", "xKey", "yKey"}`; anything else leaves both empty. The frontend draws one x column, so a chart labelled by first and last name uses the first.

Health and the model list remain public. Authentication requires the enabled private app DB at schema 6 and a valid session secret. Only new Google config/callbacks require the Google client ID; valid durable sessions can be checked and logged out during provider configuration failure. Invalid/expired sessions return 401, CSRF or dataset denial 403, bounded admission 429 with Retry-After, and unavailable storage/config/provider 503. Validation 422 responses contain a fixed detail string without reflecting submitted credentials/prompts. All `/api` responses use no-store.

The auth response user is `{id,email,name,picture}`, where `id` is the canonical UUID; never fabricate a Google subject. Capabilities are explicit booleans (`google_login`, `password_login` (feature flag, default false), `durable_sessions=true`). The browser facade validates that contract and keys workspace state by canonical ID. Confirmed logout/401/account switch clears private state and aborts old requests. Pending/failed logout retains a hidden, inert workspace with retry; it never reports completion before server confirmation.

Google identity is keyed by verified issuer/subject, never automatic email linking. Fresh approved Gmail/Workspace email or explicit subject evidence may seed an absent durable grant for the server-configured dataset. Revoked grants stay revoked on re-login. Every authenticated operation checks account status/epoch/session expiry/revocation and current grant state; current config approval also gates legacy-derived grants. General login grants no analytical permission. Routes remain same-origin, preserve HTTPS Secure/HttpOnly/host-only cookies, Origin/CSRF and nginx SPA routing. See `docs/google-signin.md` and `docs/ops/P03_IDENTITY_CUTOVER.md`.

### P04 password API (reviewed production activation complete)

All new routes use `/api/v1/auth`, server-controlled flags and enabled schema-5
storage. They never require Google configuration. `GET /bootstrap?action=...`
returns action-bound CSRF and an opaque `__Host-aqua_password` cookie; accepted
actions are registration, verification, login, reset-request and reset. Each
unsafe action consumes that challenge once after exact Origin/CSRF checks.

| Route | Body / successful response |
| --- | --- |
| `POST /api/v1/auth/registrations` | `{email}` only, generic 202; never store a pending password/account |
| `POST /api/v1/auth/email-verifications` | `{token,password}`, establish fresh password with mailbox proof, 204/no automatic login |
| `POST /api/v1/auth/password-login` | `{email,password}`, canonical session response; rotate opaque token |
| `POST /api/v1/auth/password-reset-requests` | `{email}`, same generic 202 for known/unknown/Google-only addresses |
| `POST /api/v1/auth/password-resets` | `{token,password}`, existing verified password identity only; epoch/session/link revocation and notice in one transaction; 204/no automatic login |

New accounts get no dataset grant. No email auto-link or unauthenticated first
password for Google-only users. Password email syntax is ASCII/case-insensitive,
with dots/plus suffixes preserved. Passwords normalize NFC, require 15..128 code
points and <=512 UTF-8 bytes, accept spaces/managers, and compare against a pinned
local common-password corpus. No password leaves for a third-party lookup.
Argon2id uses 19456KiB/t2/p1, two global request-hash slots and no leased DB
connection during hashing. Corrupt/absent credential rows do real dummy work.
Hash slots fail closed after a crash; stop all hash workers before operator
recovery. Settings cannot change these limits.

`PASSWORD_AUTH_ENABLED`, `PASSWORD_REGISTRATION_ENABLED` and
`PASSWORD_RECOVERY_ENABLED` all default false and are independent controls.
Verification/reset TTLs default 86400/1800 seconds. `ACCOUNT_MAIL_ENABLED`, a
separate 32-byte `ACCOUNT_MAIL_OUTBOX_KEY` and `ACCOUNT_PUBLIC_ORIGIN` configure
encrypted temporary mail. Only the explicit worker receives `RESEND_API_KEY`;
never supply it to the web process or frontend. Default worker flag is disabled.
P04 does not install a scheduler, send real messages or implement P05 forms.
See `docs/ops/P04_PASSWORD_CUTOVER.md` and `docs/ops/P04_ACCOUNT_MAIL.md`.

The pre-merge follow-up adds recipient/purpose five-minute cooldown, three new
logical messages per rolling 24h and pending-job coalescing, backed by bounded
independent history. Mail templates and proof bindings are fixed. Keep these
server controls outside Settings. Answer Markdown allows formatting only: no
images, active generated links or raw HTML; clipboard/CSV text neutralizes
spreadsheet formulas. SQL operator/type/catalog resolution follows the central
approved-call policy. See `docs/implementation/P04_SECURITY_REVIEW.md`.

Bootstrap budgets are shared anonymous aggregates behind the tunnel, so abuse
can temporarily return 429 to other visitors' bootstrap attempts. Independent POST zones
and mail allocations prevent registration from spending those specific recovery
budgets; they are not end-to-end availability or measured capacity guarantees.

Charts use the existing `visualizations` and `kpis` fields described above; there is no separate `chart` field. Ben owns `visualize.py` and decides any change to how charts are chosen or shaped.

P01 nginx answers 429 above 10 questions a minute per socket peer (burst of 5; a shared aggregate behind the local tunnel), with separate Google verification 5/minute plus burst 3 and login-bootstrap 10/minute plus burst 5 budgets; the client shows that as a retryable "slow down" message. The UI shows `sql` under every answer, and under refused queries as the SQL that was not run. `model` names the model that actually answered (empty for outages); it differs from the one requested after a fallback to Ollama, and the UI shows it as "Answered by".

## Pipeline

1. Receive a question.
2. Build context from a reviewed bank/Pagila manifest, catalog identifiers and static code dictionaries. Never sample row values or live comments for prompts. With retrieval, validate selected relations/examples and rebuild the schema text. Only classified availability failures may fall back within the same authorized manifest; authorization/integrity/unknown failures stop.
3. Ask the model (Gemini Flash-Lite by default; Ollama, then Gemma 4 26B, when it is out of quota or down) for one SQL statement. With `ANSWER_SIZE_RULES=on`, `answer_size.py` adds one line saying how many rows the question wants: the number it gives, the top 10 for a plural with no number, first place and every tie for a singular, the same within each group for "in each", and no limit for "all".
4. Validate the SQL with `validate.py` against the schema's allowlist. On failure, never execute.
5. Execute in a read-only transaction with a row limit and timeout.
6. For an eligible validation or SQLSTATE failure, ask the model once more with the previous SQL and a fixed diagnostic code/message. Raw database/provider exceptions never reach repair prompts, clients or boundary logs. Permission failures, timeouts and unknown errors are not repaired.
7. Summarize the rows, pick a chart, and return rows, summary, chart and SQL. The summary says when the default top 10 was applied, or when several rows tie for first place.

Before cache lookup, `main.py` checks the current session and dataset allowlist. Keys preserve exact question text and include server-owned principal, dataset, authorization/schema/policy/context revisions and provider settings. Successes expire at `ANSWER_CACHE_SECONDS` (600 by default); failures are never cached. LRU storage is capped at 256 entries, 1 MiB encoded per entry and 16 MiB encoded total; object overhead is additional. See `docs/security/P01_BOUNDARIES.md` for costs and limitations.

## Safety rules (non-negotiable)

Two independent layers. Both must exist; neither replaces the other.

Layer 1, `validate.py`, parses with sqlglot and rejects anything that is not exactly:

- one statement
- a `SELECT`, optionally with `WITH` CTEs that are themselves read-only
- touching only tables on the allowlist (Pagila tables; never the retrieval or query-log tables)
- free of DML, DDL, `COPY`, `SET`, `CALL`, `DO`, transaction control, and data-modifying CTEs
- free of dangerous functions (for example `pg_sleep`, `pg_read_file`, `pg_read_binary_file`, `lo_import`, `lo_export`, `dblink`, `set_config`)

Validation walks the AST. Never validate by string matching for keywords like `DROP`.

Execution also enforces a `LIMIT` (add one if missing, cap it if too large).

Layer 2 is the database role. The app connects only as `nl2sql_reader`, which has `SELECT` only, `default_transaction_read_only = on`, and `statement_timeout = 10s`. The `SELECT`-only grant is what actually blocks writes, because a session can turn the read-only default off; layer 1 rejecting `SET` covers that path.

The admin account (`tsdbadmin`) must never appear in app code, `.env`, docker-compose, or tests. It is used only by a human running `db/` scripts with `ADMIN_URL` exported in their shell. Tableau also connects with a read-only role, never the admin account.

Hidden columns (`staff.password`, `staff.picture`) are refused at both layers: the validator rejects any query that names them, selects `*` from `staff`, or uses the whole row, and `db/05_hide_columns.sql` replaces the reader's table grant on `staff` with column grants. `schema.py` never shows them to the model.

The offline embedding indexer connects as `nl2sql_indexer` through `INDEXER_DATABASE_URL`. That role can write only to the `retrieval` schema and has no grants on `public`. The web app never uses it. The reader can `SELECT` from `retrieval` for similarity search, but the validator's allowlist must never include retrieval tables, so generated SQL cannot read them.

## Environment variables

```
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:8b
OLLAMA_THINK=true
LLM_PROVIDER=gemini
LLM_FALLBACK=on
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.5-flash-lite
GEMINI_FALLBACK_MODELS=gemma-4-26b-a4b-it
GEMINI_EMBED_MODEL=gemini-embedding-2
DATABASE_URL=postgresql://nl2sql_reader:CHANGE_ME@HOST:PORT/tsdb?sslmode=require
INDEXER_DATABASE_URL=postgresql://nl2sql_indexer:CHANGE_ME@HOST:PORT/tsdb?sslmode=require
RETRIEVAL=off
ANSWER_SIZE_RULES=on
ANSWER_CACHE_SECONDS=600
GOOGLE_CLIENT_ID=
SESSION_SECRET=
APP_ORIGIN=https://aqua-ai.us
SESSION_MAX_AGE_SECONDS=3600
AUTH_MAX_SESSIONS=5
AUTH_IDLE_SECONDS=1800
AUTH_ALLOWED_EMAILS=
AUTH_ALLOWED_GOOGLE_SUBS=
```

Production sets `RETRIEVAL=on` once the index is built (see Commands). Read analytical/model settings only through `backend/nl2sql/config.py`; new `APP_STORAGE_ENABLED`, `APP_DATABASE_URL` and bounded pool settings are separately validated by `backend/storage/config.py`. Never use the analytical URL as a storage fallback. docker-compose passes `.env` to the backend container. Gemini rate limits are per Google Cloud project, so each developer uses an AI Studio key from their own project and the server at `/srv/bank-ai` uses a separate one.

`SESSION_SECRET` must contain at least 32 characters and be randomly generated; never expose it to the frontend. Session lifetime is 300 through 86400 seconds. `APP_ORIGIN` is the browser's exact HTTPS origin; loopback HTTP is supported for local development. Account allowlists are comma-separated and are checked before any schema, database, or model work. They govern the single configured database, not customer database selection. P03 connects identity tables to Google auth. AUTH_MAX_SESSIONS defaults to 5 (1..20), AUTH_IDLE_SECONDS to 1800 (60..3600), and absolute lifetime to 3600 (300..86400). GET polling never extends idle lifetime. Login budgets persist across sessions/workers; they do not replace P07 AI job/global admission. Limits are server policy, never preference values. See `ops/appdb/README.md` for the reviewed installation/backup/restore procedure.

## Historical research phases

These original research phase numbers predate the current P00–P13 product
implementation order in `AQUA_CODEX_HANDOFF.md`. In particular, the research
logging backlog below is not P07 durable analysis. Use the handoff checkpoint
at the top of this guide for current status and next-phase authorization.

| Phase | Goal | Done when | Status |
|---|---|---|---|
| 0 | Repo scaffolding | Layout above exists, CI runs pytest and black | Done; current P07 release and all required checks verified |
| 1 | Database | Pagila loaded, reader role works, write test fails as expected | Done |
| 2 | Baseline pipeline | `/api/query` returns validated SQL and rows; full schema in prompt | Done |
| 3 | Evaluation harness | Execution accuracy reported on a fixed question set | Done; results in `docs/decisions.md` |
| 4 | Retrieval layer | Relevant tables and examples retrieved per question; accuracy compared to Phase 3 | Done; helps qwen3:4b, no measurable difference for Gemma 4 on this set |
| 5 | Validation hardening | Adversarial test suite passes | Done |
| 6 | React interface | Shows question, SQL, rows, and summary; served on the project domain as a production build | Done and live; see current P07 checkpoint |
| 7 | Logging and learning loop | Queries logged; good ones feed the example store | Not started |

Work one phase at a time. Do not build ahead. Frontend work can run alongside backend phases as long as it codes against the API contract above.

### Open items

Agreed but not started. Each needs its own change and a `docs/decisions.md` entry when done.

- Phase 7 logging: `db/06_logging.sql` with a `query_log` table and an insert-only `nl2sql_logger` role, `nl2sql/querylog.py`, and a way to promote checked pairs into `retrieval.example_query` as `query_log` rows.
- Tableau: `db/07_tableau_role.sql`, a read-only `tableau_reader` without the 10-second timeout and with the same hidden staff columns.
- A second, harder question set (`eval/datasets/pagila_v2.jsonl`), written before looking at model output, so the retrieval comparison rests on more than 50 questions.
Completed product phases P05 activation, P06 workspace and P07 analysis are
live and verified. See the current checkpoint and
`docs/implementation/P07_DURABLE_ANALYSIS.md`; the older research backlog above
does not reopen completed product work.

P05 presentation rollback uses build-time `VITE_AQUA_UI_SHELL=opal|legacy`, exposed
through Docker/Compose `AQUA_UI_SHELL` (default `opal`, invalid values rejected).
Both variants must share current authentication, account ownership, routes,
semantic composer and mobile dialog. Never restore obsolete auth components or
change a backend/security flag to switch appearance. Rebuild only the frontend;
retain the current schema-5 backend/private-storage overlay. The legacy shell must retain
password-only access. Existing account ownership survives legal/Back navigation
while logout is unresolved; direct public policy visits need no auth bootstrap.

- Modules over the size guideline: `schema.py`, `validate.py`, `retrieval/store.py`.
- Fine-tuning an open model (after Phase 7, optional).

## Conventions

- Type hints on every public Python function.
- Docstrings explain why, not what.
- No module over about 200 lines.
- No bare `except:`; catch specific exceptions.
- Format Python with black, default settings.
- Never commit `.env`, `.venv/`, `node_modules/`, database dumps, or eval results.
- Add new dependencies only when needed, and say why in the change description.
- `requirements-ml.txt` is for the fine-tuning stack only; runtime dependencies go in `requirements.txt`.
- Any significant choice gets an entry in `docs/decisions.md`: the decision, alternatives, reasoning.

## Commands

Local backend development (run from `backend/`):

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env       # then fill in values
python -m nl2sql.db              # connection smoke test
python -m nl2sql.schema          # print the schema the model sees
pytest
black .
uvicorn main:app --reload --port 8000
python -m nl2sql.retrieval.store # embed schema and train examples (needs INDEXER_DATABASE_URL)
```

Evaluation (run from the repo root, backend venv active; the model must be reachable):

```bash
python eval/run_eval.py --check-gold   # gold SQL only, no model calls
python eval/run_eval.py                # baseline: every table, no examples
python eval/run_eval.py --retrieval    # with retrieval, for the Phase 4 comparison
```

Local frontend development (run from `frontend/`; the backend must be running on port 8000, or set `VITE_AQUA_DEMO_MODE=true` to work offline):

```bash
npm install
npm run dev
npm test
```

Server: follow `docs/ops/P04_PASSWORD_CUTOVER.md` for the reviewed migration and image checks. Routine updates after cutover must retain the storage overlay; startup never migrates:

```bash
git pull --ff-only origin main
export AQUA_PRIVATE_STORAGE_DIR=/home/ben2004/.aqua-runtime/app-storage
docker compose -f docker-compose.yml -f compose.app-storage.yml up -d --build
curl --fail --silent localhost:8000/api/health
curl --fail --silent localhost:8000/api/ready
```

## Rules for agents

### Security gate for every new user action

For every new or changed button, form, menu action, renderer or API operation,
map the action to the server-side permission and data/resource boundary before
calling it complete. Test direct API calls with forged/extra fields and foreign
IDs, missing/expired/revoked sessions and CSRF, malicious text/HTML/URLs/SQL or
spreadsheet content as applicable, replay/concurrent submissions and relevant
rate/queue/provider limits. Assert that rejected requests perform no unauthorized
database, file, model, email or network work. Pair the attack cases with normal
authorized behavior and cooldown/failure recovery. A hidden/disabled UI control
never substitutes for backend enforcement. Use isolated fixtures/fake providers,
retain findings and passing regressions, and fix sensitive-boundary failures
before the human PR checkpoint. No unrestricted production attacks are implied.
Keep future charts, Settings imports and AI tools data-only and allowlisted.


- On October 28 the user explicitly authorized Codex to handle all Git operations through the remaining phases: branch, commit, push, create PRs and merge after required checks pass. Use short commit titles such as `Phase9 Settings` and `Phase9 Homepage`. Preserve phase isolation and security/release gates.
- Do not create, modify, or delete Tiger Cloud services. Use database tools in read-only mode.
- Do not run DDL or write queries against the shared database. Schema changes go in `db/*.sql` for a human to apply.
- Write or update tests in `backend/tests/test_validate.py` before changing `validate.py`.
- Mock the LLM in unit tests; do not spend API quota in pytest.
- Do not change the `/api` contract without updating this file and telling the frontend owner.
- If a task conflicts with this file, stop and ask.
