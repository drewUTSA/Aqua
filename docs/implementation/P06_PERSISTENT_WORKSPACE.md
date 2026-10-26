# P06 persistent workspace — deployed October 26, 2026

**Status: P06 implementation, required PR/main checks, private migration,
deployment and controlled production verification passed.** The live site uses
the tested schema-4 release at `6872e41` (PR #46). P05 email/password activation
remains enabled. P07 has not started and is outside this authorized run.

## Resulting behavior

Live authenticated sessions use durable, account-owned chats, messages, flat
projects and saved prompts in the private application PostgreSQL database.
Reloading retrieves the same canonical chat/message/request IDs. Demo mode keeps
its existing fictional, in-memory behavior. The Opal and legacy presentation
variants share the same authenticated workspace and transport.

A first question creates a chat, its user message, one pending assistant reply
and an analysis request in one short transaction. Synchronous model work begins
after that transaction releases its private DB connection. Completion rechecks
the session, account, current dataset grant and undeleted chat before persisting
the bounded response. No application DB lease spans model or analytical I/O.
Existing SQL validation, authorized dataset context and read-only analytical
execution remain in the shared query implementation.

## API and ownership boundary

All routes below are under `/api/v1`, authenticated through the existing durable
session. Unsafe methods require the existing exact Origin and session CSRF.
Caller-supplied ownership, SQL, result rows and extra fields are rejected.

| Route | Contract |
| --- | --- |
| `GET /chats` | Bounded recent/archive/project page; no private search text in the URL |
| `POST /chats/search` | JSON title-prefix search, bound filters/cursor and normal CSRF; does not submit a question |
| `GET /chats/{id}` | Owned current chat metadata |
| `GET /chats/{id}/messages` | Latest messages in ascending display order, with a bounded older-page cursor |
| `POST /chats` | First question: `client_request_id`, question, optional model/project |
| `POST /chats/{id}/messages` | Append a question to an owned, unarchived chat |
| `POST /chats/{id}/messages/{input_id}/retries` | Explicit eligible retry; new client UUID, original input, one new assistant attempt |
| `PATCH /chats/{id}` | Revision-checked title, archive or owned-project assignment |
| `DELETE /chats/{id}` | Revision-checked content/result purge and hidden tombstone |
| `GET/POST /projects` | Owned bounded project list/create |
| `PATCH/DELETE /projects/{id}` | Revision-checked rename/archive or content-purging deletion; deletion detaches owned chats |
| `GET/POST /me/saved-prompts` | Owned bounded prompt list/create |
| `PATCH/DELETE /me/saved-prompts/{id}` | Revision-checked text/pin changes or content-purging deletion |
| `POST /me/saved-prompts/{id}/uses` | Idempotent usage count; applying a prompt never executes it |
| `GET /starter-prompts` | Fixed curated examples, separate from private saved prompts |

UUID ownership is derived from the authenticated canonical account and checked
on each parent/child query. Composite database foreign keys independently reject
cross-owner projects, messages, replies and results. Foreign/missing resources
produce the same fixed 404 response. Row locks follow the user/session/grant
order for short private transactions; logout/reset/grant changes cannot commit
between those checks and the protected transaction's work.

Metadata and the user's own input remain private to that account. A dataset grant
is separately required before any new analytical request. Historical assistant
content, SQL, rows, charts and KPIs are withheld when current data access is
absent or the stored dataset differs. The browser also masks current and late
history/submission responses on confirmed grant loss; account switches and
confirmed logout discard their old workspace state.

## Replay, deletion and recovery

Submission client UUIDs are unique per account. Identical transport replay
returns the same IDs/state; changed input under that UUID returns 409. An inflight
replay returns 202 and never starts another model call. Message sequence numbers
are reserved before model work, so out-of-order completion preserves the original
input/reply order. Explicit retries reuse the original input but receive a new
request and assistant ID.

Deletion purges chat input/result content or project/prompt text and retains
bounded hidden identity/idempotency metadata. Lists, direct reads, parent checks
and replay reject deleted rows. A late create replay cannot recreate a deleted
catalog item. Deleting a project detaches its chats; deleting a saved prompt also
removes its usage records. Deletion is not a claim that historical backups have
been erased.

Pending requests older than two hours are marked interrupted and release their
reservation once. This is a conservative abandoned-web-request fence, not a
background job scheduler. Late completion cannot revive an interrupted/deleted
request. Browser Stop ends only the browser request: the UI preserves an uncertain
operation and its original UUID, and checks saved state without creating duplicate
work. No server-side cancellation guarantee is made.

The restore fence remains compatible with schema-3 backups. For schema 4 it also
interrupts restored pending requests/messages and refunds their reservations
once while preserving completed owned history. It still advances account epochs,
revokes sessions, consumes proofs and cancels restored pending mail. It is for a
separate detached recovery database with workers stopped, never routine live
cleanup.

## Bounds and privacy

| Resource | Released bound |
| --- | --- |
| Mutation body | 16 KiB before JSON parsing |
| Question/prompt | 2,000 characters; 8,000 UTF-8 bytes for stored text |
| Names/titles | 120 characters |
| Chat messages | 200 per chat |
| Chats | 100 nondeleted / 1,000 retained per account; 10,000 global |
| Analysis requests | 10,000 per account; 100,000 global |
| Projects | 20 nondeleted / 1,000 retained per account; 50,000 global |
| Saved prompts | 100 nondeleted / 1,000 retained per account; 50,000 global |
| Prompt use records | 10,000 per account |
| Logical stored content | 16 MiB per account; 200 MiB global |
| Workspace mutations | 60 per account/minute, including rejected item/revision attempts |

Short advisory-lock bookkeeping serializes global reservations. A fixed singleton
counter avoids a history scan for global byte admission. These are logical-content
and row caps, not physical PostgreSQL disk-size or production performance claims.
P07/P12 still own broader job admission and capacity work.

Lists use bounded keyset pages and owner indexes. Signed cursors bind the account,
list filters and stable sort position; offset pagination and arbitrary message
body search are not implemented. Search text travels in POST JSON rather than
query strings, including at the Cloudflare boundary. Private workspace access
logging is suppressed/redacted at the origin as additional protection. Responses
use no-store and fixed safe failures, never raw driver/provider diagnostics.

The browser preserves unsent drafts across its own chat navigation and failed
actions. It bounds active transcript caches and concurrent browser submissions,
aborts superseded reads, and prevents stale responses from restoring deleted or
other-account state. Drafts are page-memory state; this phase does not promise
offline storage or durable drafts across reloads.

## Verification and migration

The deployed backend image is
`sha256:22d0c0496c7f4d25528dd41efb0f66b1c99585a1037ed3304e54142979ff3552`.
Its actual-image matrix passed all 1,181 distinct tests across the bank and
Pagila disposable fixtures. Installer, schema-3 compatibility, schema-4 restore
fencing and the actual Uvicorn privacy probe passed with cleanup confirmed.
Source/lock checks, Black, Ruff and the 24 fixture safety checks passed.

The isolated proxy red test used the previous production configuration and
admitted all 12 mixed legacy/new-chat questions, exceeding the shared maximum
of six. The repaired configuration passed 113 bounded requests, shared question
admission, personal-metadata availability, denial and recovery. Both runs used
network-none containers and a fake upstream; cleanup and absence were confirmed.
Credential-free evidence is in `.check-results/p06-release/proxy-red-before.json`
and `proxy-report.json`. Neither test contacted the production application.

Final frontend validation passed all 195 unit tests and, for each of Opal and
classic, 92 synthetic browser checks and 30 actual FastAPI/private-PostgreSQL
browser checks. The optional analytical fixture returned fixed synthetic data;
the real provider-call count remained zero. These covered canonical chat
creation/reload, replay, explicit retry, grant revocation, foreign ownership,
private catalogs, held-response races and enlarged-text/mobile controls. All
browser profiles, listeners and fixture resources were removed and absence
confirmed. Root independently reviewed the final screenshots.

The exact public asset sets and nginx configuration were verified inside both
immutable release images, with no extra public files. The actual Opal image
also passed the 113-request isolated proxy gate. Images:

- Opal: `sha256:ab666543d121d7e744f5bf7f1e6cc20eda7e38df3c777d193a8de708f22feede`.
- Classic rollback: `sha256:99f88957b40199851d9cea9960a12910d24103ef0be564aa4612fe49b9c236dc`.

PR #46 merged at `6872e416c2b8518e3fcaf649595c749b3a5d1ff5` after required
CI run `40419937750` passed all 25 steps on its exact reviewed head.
Merged-main run `40420889566` also passed all 25 steps with no failures or skips.

`0004_workspace.sql` is additive private app-DB schema 4. Applied migrations
0001–0003 remain immutable. Production startup does not run DDL. The new backend
requires explicit reviewed migration/readiness; the hosted analytical database,
its credentials and schema are outside this change. Preserve the existing private
data/socket volumes and encrypted backup/recovery material. Do not use `down -v`
or a schema-3 image as a rollback after migration; use a schema-compatible forward
fix or maintenance state.

Pause the reviewed account-mail schedule for the cutover and stop the old backend
before applying migration 4. Start the exact tested schema-4 backend, require
healthy internal readiness, and resume the worker only when its local backend
image tag identifies that same compatible release. Preserve queued mail, keys and
delivery budgets throughout; neither a recreate nor migration authorizes replay.

## Completed production cutover

The reviewed mail schedule was paused and its existing singleton lock held in
a live guard through backup/migration. The old backend stopped before export.
The fresh private schema-3 snapshot
`pre-p06-20261026T234428Z.pgdump.age` was streamed directly into encrypted
off-server storage. Authenticated decryption matched the export and the separate
recovery identity was verified; no plaintext dump was saved or printed. Its
encrypted SHA-256 is
`ade8da5a59c137eafd8b3c6a2f5e1772d3b46442748b311330cfe4359ab719fa`.
The identity stays separately protected in local AppData. The operator/server
clock offset was checked and accommodated before export so the backup passed
the post-writer-stop timestamp gate.

Explicit private migration 4 succeeded, then the exact tested backend and Opal
images were deployed. Healthy backend container
`6c94468469eca907e6833081a246fd5b17b6347c7d8e7a3232b0c2767aa64974`
reports schema 4; frontend container
`52805de860f5e32da48e13f9881271bd2c76f60a4db955a6a71746befa77f470`
serves the reviewed artifact. The existing private database container
`5d0ab1293dd015846de301c7d732933d595538118ae535e4cb7f13951bcfd427`
and its volumes were retained, with no TCP exposure and the read-only backend
socket mount preserved. Migration changed no authentication activation flags.
Password login, registration, recovery and encrypted mail remain enabled;
provider credentials stay outside the web process and its worker flag stays off.

The root-executed production catalog probe completed exactly 23 HTTP calls on
the dedicated controlled P05 account. It proved project/prompt create, edit,
literal prompt use, same-use replay, reload, deletion, deleted-create replay
404s, logout and old-cookie rejection. The account retained no dataset grant;
no chat, analytical/model call or mail was created, and no normal user's data
was touched. Both catalogs finished empty. The uniquely labelled loopback
canary was removed and its absence confirmed; its state remained encrypted.

The exact original cron content was restored only after schema-4 readiness and
the compatible backend tag were verified, then the singleton guard exited
successfully. Scheduled worker invocations reported `idle` at 23:47:02 and
23:48:01 UTC after resumption, with cron active and exactly one managed entry.
No leases, delivery attempts or quotas were reset.

Public root, sign-in and health returned 200; anonymous identity returned 401;
public readiness remained 404. Cloudflare's live files exactly matched the
frontend container:

| Asset | SHA-256 |
| --- | --- |
| `/assets/index-BW2ecYLk.js` | `bf5269d119131f7bf825315220194cc78ec7e0ebac19a59f0b80edb456a81f17` |
| `/assets/index-Bt5w1vE3.css` | `3090999f68aa4e3c6ba2ec2a306b6aa725308114e2e6904cca267042eb44df6c` |

A clean Chrome profile loaded the actual public sign-in page and confirmed
enabled email/password controls and registration/recovery links using those
assets. Root reviewed its screenshot; browser/profile cleanup passed. No
authenticated account was used by that public browser check.

Credential-free evidence is under `.check-results/p06-release/`: `deployment.json`,
`postdeploy-20261026T234546Z.json`, `controlled-catalog-smoke.json`,
`cutover-state.json`, `public-browser.json` and the encrypted backup metadata.
Post-cutover scheduled execution is recorded in `schedule-proof.json`.
Do not commit private environments, capsules, keys, passwords or bearer values.

The backup result establishes snapshot integrity, not a production restore or
measured RPO/RTO. Restore and attack/load exercises used detached disposable
fixtures. No live model/financial-data exercise, real Google identity login,
production disaster-recovery cutover or P07 asynchronous-job work is claimed.
