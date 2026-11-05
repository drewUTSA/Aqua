# P11a private JSON exports — candidate verification

This is the isolated P11a candidate in p11-work. It has not passed the full
canonical or real-browser release gates and is not deployed. Local modeled tests
are evidence only for their explicit fake boundaries; authored PostgreSQL,
capacity, restore and browser cases are not passed merely by existing. P11a is a
bounded temporary data copy, not account deletion or a backup mechanism.

PRIVATE_DATA_EXPORT_ENABLED defaults off. Activation additionally requires the
reviewed single-container/single-web-process topology, exact Uvicorn argv, four
web pool connections, one worker connection and two download connections, with
the existing one-connection mail worker. Runtime role limit12 and planned total
<=10 remain unchanged; this allowed topology plans eight. See
[activation evidence](../security/P11A_EXPORT_ACTIVATION.md). The operator must
verify actual host/container absence; this process cannot infer that from its
isolated PID namespace. Multiple containers/processes remain unsupported.

A process-wide two-stream/one-owner physical registry survives database-session
loss and remains held until the real ASGI send/task and connection cleanup stop.
Session advisory locks remain an additional defense, not a distributed physical
concurrency guarantee after DB restart or backend termination. Pure-ASGI cache
header middleware keeps ownership around the real send rather than an internal
buffering channel. Actual terminated-backend/blocked-send tests are required.

## Public contract

Fixed scope `personal_v1`, format JSON only. A client generates a canonical
intent UUID once when the user begins a deliberate export flow. Recent password
or Google proof uses operation `data_export`, `target_intent_id:<UUID>` and no
other target field. Server target hashing binds both fixed scope personal_v1 and
the exact UUID; existing operation digest bytes remain unchanged. Proof lifetime
is still 300 seconds, with existing 5/account/minute and 30/global/minute durable
admission, current credential/active-Google revision, owner/session/epoch and
one-use checks. Polling never refreshes proof or session idle authority.

Reuse the existing `preferences.capabilities.private_data_export` server flag
(currently false); do not add a new key to C's strict account capability DTO.
The server exposes it only when this full operation and worker/schema boundary
are available. It is independent of preference values/import/reset. The UI also
requires a currently usable proof method; all authorization remains server-side.
History/account deletion capabilities stay false in this export-only slice.

- POST `/api/v1/me/data-exports`: closed body
  `{intent_id,scope:"personal_v1",proof_token}`; <=16 KiB; canonical current
  cookie/CSRF/Origin before SQL; no owner/path/format/perms/expiry supplied.
  Final proof consume + capacity reservation + job creation commit atomically.
- GET `/api/v1/me/data-exports/{job_id}`: exact owned job snapshot.
- GET `/api/v1/me/data-exports/by-intent/{intent_id}`: same snapshot or generic
  not-found, allowing explicit lost-creation-response reconciliation without
  replaying the consumed proof/POST. Register this static route before job-ID
  routing. It never returns another intent or owner in an error.
- GET `/api/v1/me/data-exports`: at most five owned retained jobs, active first,
  then created_at/id descending. Owner has at most five retained metadata rows,
  so no unbounded list or device-persisted identifiers are required. Fetch only
  after explicit Review exports; optional owner-bound HMAC cursor is at most
  1,024 ASCII characters. Page size stays five and unknown query fields deny.
- GET `/api/v1/me/data-exports/{job_id}/download`: same-origin fetch only with
  the captured session's in-memory `X-CSRF-Token`, checked explicitly even though
  this is GET. Reject foreign Origin when present and cross-site Fetch Metadata;
  do not require a same-origin GET to contain an Origin header a browser may
  omit. Missing/incorrect paired header denies navigation/form-triggered download.
  Same-origin cookies remain HttpOnly; no public URL, bearer query or redirect.

Job envelope:

```json
{
  "schemaVersion": 1,
  "user_id": "canonical current owner UUID",
  "job": {
    "id": "server UUID",
    "intent_id": "client intent UUID",
    "scope": "personal_v1",
    "state": "queued",
    "created_at": "server ISO timestamp",
    "expires_at": "created_at plus one hour; never extended"
  }
}
```

The common fields are exactly id, intent_id, scope, state, created_at and
expires_at. State is one of queued/working/ready/expired/failed. Ready alone adds
byte_count (exact JSON integer 1..33,554,432) and sha256 (64 lowercase hex).
Failed alone adds error_code from source_too_large, authority_changed,
interrupted, unavailable or encoding_failed; never raw DB/provider/recipient or
exception text. Queued, working and expired omit output/error fields entirely;
there are no null placeholders, completed_at or download_available fields.
List returns `{schemaVersion:1,user_id,jobs,next_cursor}` with nullable bounded
cursor. Unknown or foreign jobs return generic 404. Ready becomes terminal
expired on expiry/invalidation, and cached bytes never remain downloadable.
Unavailable may also be an ordinary safe HTTP error, not a sixth persisted state.

UNIQUE(user_id,intent_id), fixed scope and a closed fingerprint provide job
idempotency while metadata exists. Commit durable admission before failed lookup.
An exact authenticated retry can return its existing owned intent; a different
intent is never substituted and a different scope/fingerprint conflicts. Expiry
or retries do not mint proof or extend the one-hour output window. After expiry,
the UI starts a new deliberate intent/proof rather than automatically replaying.

The job captures the originating canonical session ID, auth_epoch and
privacy_epoch internally. An ended/changed originating session cannot generate,
publish or download that export through a different session. Owner-only status
may show the old job as expired/unavailable; it never upgrades its authority.

## Exact scope and serializer

Produce one closed UTF-8 JSON document with schemaVersion1 and fixed personal_v1
scope; export creation/snapshot/expiry timestamps; owned profile display name,
primary email and account creation time; safe account preferences and separately
labeled personal instructions/notification choices; nondeleted projects, saved
prompts, chats and messages. Include archived owned chats. Use flat arrays with
public chat/message/project UUID links, rather than duplicating every result in
nested message/request copies. Projects and saved prompts retain their names,
text, pin state and personal usage data. No curated/shared catalog or other user.

User-authored messages remain exportable without analytical access. Assistant
message content/response/SQL/tables/KPIs/chart specifications are included only
for the currently authorized dataset; unavailable result content is omitted with
a generic result_unavailable marker. A revoked historical dataset never becomes
available merely because its owner can export personal text. Preserve existing
exact-value metadata and stored numeric values. Select JSONB result fragments
as text and serialize only a closed public result shape; do not round-trip them
through Decimal -> float, browser numbers or a fresh summarizer/model. Bound and
validate raw JSON fragment type/size, drop unsupported top-level fields, and test
exact numeric tokens and chart metadata. No SQL is executed against business DBs.

Explicitly exclude credentials/password hashes, cookie/CSRF/session/digest data,
proof/challenge/pending-mail tokens, raw Google subject/issuer/assertions,
permissions/grants/allowlist/dataset-key internals, outbox/encrypted envelopes,
runtime configuration, error traces and analytics data. Use allowlisted field
selection, never generic `SELECT to_jsonb(user/security row)` export serialization.
Client display stays opaque: verify bytes/hash, then offer an attachment; never
render, execute or numerically reserialize private export contents.

## Fixed technical bounds

These are conservative implementation limits, not legal/security-log/backup
retention promises. They may reject a pathological valid 16 MiB workspace whose
JSON metadata/escaping exceeds the export limit; fail and clean up, never truncate.

| Resource | Bound |
| --- | --- |
| Output lifetime | Created_at + 3,600 seconds, unchanged by retry/read/download |
| Per-export serialized bytes | 33,554,432 (32 MiB, twice the current 16 MiB source quota) |
| Chunk size / count | 65,536 bytes / at most 512; last chunk may be shorter |
| Owner private-output reservation + retained bytes | At most 32 MiB, including expired output awaiting cleanup |
| Global private-output reservation + retained bytes | At most 128 MiB, separate from current 200 MiB workspace accounting |
| Owner live export | One queued/working/ready job |
| Global queued + working jobs | At most four total |
| Retained job metadata | Five/owner and 128/global; cleanup after fixed expiry |
| Worker | One global physical coordinator, one local thread per backend instance; fixed DB advisory lock |
| Worker lease / job deadline | 15 seconds / 120 seconds from acceptance; at most three crash-recovery claims within that deadline |
| Snapshot | Repeatable read, at most 10 seconds wall time; existing 3-second statement / 1-second lock / 10-second idle-in-tx bounds |
| Read batch | Named server cursor, 16 rows/fetch, fixed indexed query order and fixed table list |
| New worker memory | Target <=64 MiB extra at maximum record/Unicode/output bounds; measure under unchanged 3 GiB service cap |
| Download streams | Two global physical slots and one per owner, held by DB session advisory locks |
| Download deadlines | 60 seconds total, 2 seconds per ASGI send; no TTL-based physical-slot release |
| Download attempts | Five/owner/minute and 20/global/minute, persisted, failures spend admission |
| Status/list/by-intent reads | Existing shared metadata 60/account/minute; no per-chunk user admission charge |
| Cleanup step | At most 64 chunks (4 MiB), then bounded job metadata; retryable and fenced |

Reserve 32 MiB before generation, release only unused reservation on successful
publish, and retain actual-byte accounting until chunks are actually deleted.
Partial chunks never evade the same owner/global cap. A retry retires its old
unpublished generation before writing a replacement. Completed or failed job
metadata is kept only within this technical one-hour job window; this does not
set audit retention. Existing auth/mail/analysis/Argon2 limits are unchanged.

## Lifecycle, pools and physical ownership

Source inspection: main.py42–68 already starts/stops Analysis under FastAPI
lifespan; Analysis shares app.state.storage. Its two children use a payload
allowlist without APP_DATABASE_URL and open no application-storage pool. Existing
mail launcher is a separately activated one-connection service. There is no
reason to create a second scheduler, filesystem writer, external service or key.

Choose a DB-only PrivacyExportService owned by that same lifespan. It has one
local worker thread and one dedicated runtime connection (one waiter, one-second
acquisition), isolated from web/account connection leases. It takes one fixed
global DB session advisory lock in autocommit before acting as worker and holds
that physical ownership between bounded transactions. Another process cannot
claim a physical worker merely because the 15-second logical lease elapsed.
A stalled live owner fails closed; connection/process death releases the lock.
Every append/publish still matches exact job lease owner/generation/expiry.

Use a separate bounded two-connection download pool. Each connection holds one
of two fixed global session advisory slots and the owner's deterministic
advisory lock throughout the physical ASGI send/task, in autocommit between
short per-chunk transactions. A busy owner lock releases its attempted global
slot immediately. A 5-second heartbeat is not a physical concurrency guarantee
and does not authorize another stream while an old send is blocked. Hard task
and send deadlines cancel the old task; finally unlock/reset or close the exact
connection. Do not publish a slot as free until DB ownership is actually released.
Connection-loss handling must stop bytes immediately; old buffered/already
delivered bytes cannot be retroactively recalled. Uncertain connection cleanup
fails closed. Use no long snapshot transaction for network delivery.

All short privacy bookkeeping transactions acquire privacy-global -> user -> job
locks uniformly. Existing fresh-proof/action admission is a separate committed
transaction before that order. No existing user-locked path may take privacy
global locks. Content deletion increments privacy_epoch under its existing user
lock and commits; worker cleanup later acquires its own ordered locks.

Snapshot capture owns only its job row while reading a repeatable snapshot with
plain MVCC owner/session/grant reads and writing unpublished chunks. It must not
acquire global/user row locks while holding that job. Release the snapshot/job
transaction before a fresh global -> user -> job publication transaction. Worker
physical advisory ownership prevents a second writer; lease-generation CAS and
current epoch checks protect stale resumed work. All chunks remain unpublished
until successful final authority/size/hash verification.

Bootstrap sets runtime ROLE CONNECTION LIMIT12, migrator2, backup2, app DB24 and
cluster32. Web Storage defaults to four connections; production's actual pool P
and uvicorn process count N must be measured by metadata-only release preflight.
New worst-case runtime use is N*(P + worker1 + download2) + mail1. Only N1/P4
is supported by this candidate. At current
single-process/default P4 this is eight, leaving four runtime slots. Require
total <=10 to reserve at least two runtime probe/operator slots; deny activation
if actual process/pool/other runtime-client inventory breaks the budget. Do not
silently reduce existing pools, raise the role cap or assume the extra three
connections are free. Backups/migrations use separate existing role budgets.

The backend remains 3 GiB RAM / four CPUs / 256 PIDs; its two analytical children
retain 768 MiB address-space caps each. Privacy adds one worker thread and pool
maintenance threads, not a provider subprocess. Cursor batches + at most one raw
bounded result fragment and current 64 KiB chunk avoid a full-output/double-copy
allocation. Measure worst-case Unicode/JSON escaping, tiny-row metadata overhead,
two concurrent slow downloads and existing analysis before considering the
resource proof passed. If it does not fit, reduce work/batches or fail closed;
this draft does not authorize a higher service or database resource limit.

## Authority, consistency and deletion fences

Capture a consistent repeatable-read snapshot. Read only fixed user-scoped,
indexed tables; named cursors avoid buffering all rows. Do not hold a user lock
or web pool lease while encoding/writing output or sending bytes. Snapshot grant
state and dataset identity are private job metadata, never export permission
rows. The final publish transaction independently rechecks the current origin
session, active account, auth_epoch and privacy_epoch. If any assistant data was
included, it also requires the exact currently allowed dataset/grant version
captured for that data. A no-results personal export does not gain results if a
new grant appears later. Revoke/regrant must not revive an older prepared result.

Before every 64 KiB database chunk leaves the server, reacquire fresh canonical
owner/session/account/epoch/job/expiry/grant checks on the held dedicated
download connection, release that short transaction, then send. Any mismatch
stops remaining bytes and releases physical ownership safely. Headers are
attachment JSON UTF-8, no-store, nosniff, fixed AQUA filename, no redirect or
public download token; disable nginx response buffering for this path.

Add users.privacy_epoch default1 and job-captured epoch for later P11 history and
account purge. Existing explicit chat/project/saved-prompt DELETE operations
must advance the epoch as part of their owned transaction so an already prepared
export cannot newly deliver deleted content. They need not synchronously delete
all chunks while holding the user lock. A consistent snapshot may represent
ordinary edits as-of snapshot_at; it must not survive an explicit deletion fence.
Authenticated logout/recovery/password/method/email changes are already covered
by session and auth_epoch. Restore conditionally expires all restored export
jobs/leases and deletes private chunks before reopening; it never resumes a
ready export under a new session.

## UI and policy facts

Use five states and generic preparing feedback, without fabricated progress
percentages or inbox/provider claims. Keep pending proof/intent/job and buffers
scoped to the captured owner+CSRF generation. Reload lists the five owned jobs
explicitly; no localStorage/IndexedDB, URL or broadcast bearer is required. Lost
POST replies reconcile by exact intent GET; never automatically replay mutation
or proof. Verify length/byte cap/SHA before offering an opaque download. A hash
failure or partial stream offers no file and clears memory. New expiry, logout,
owner/CSRF switch, background/inert private UI or revoked authority clears held
data; it cannot erase a file the user already downloaded.

The user's encrypted-backup retention decision is 30 days, recorded separately
in retention-decision.json; pruning is still disabled and no existing backup was
deleted. Export's one-hour DB cache is independent. The user also selected recovery targets of 24-hour RPO and four-hour RTO; those
are unmeasured targets, not achieved backup/recovery guarantees. Thirty days does not define
active-content or audit/retirement-ledger retention. P11 deletion/recovery must
retain reconciliation authority for every still-restorable older backup and
in-progress restore/download/work, including legacy backups not yet physically
pruned. Do not expire tombstones at day30 merely because a policy was recorded.
Do not claim backups are already aged out. Existing displayed contact is
Benjamin / Spear.g.benjamin@gmail.com in LegalPage.jsx; actual support operations
are not verified by this source review. Public policy copy must describe durable
private history truthfully when its actual P11 release is made.

Required gates: immutable previous migrations and additive schema8 rollback/
repeat/default/role/FK/index checks; all prior test identities and both datasets;
strict current-cookie CSRF before SQL; proof intent substitution, duplicate and
uncertain reply tests; private-byte/source/telemetry checks; current grants at
capture/publish/every chunk; owner/session/privacy changes and revoke/regrant;
JSON exact-number/Unicode/size failure without truncation; crash/restart after
every chunk/CAS and actual restored-clone output invalidation; global physical
worker/download caps under paused threads, blocked ASGI sends, process death and
multiple pools; role/pool exhaustion recovery; exact byte accounting once;
both UI shells, keyboard/mobile/200%-text/hash-failure flows; unchanged proxy
budgets and route-alias cases; no provider/mail/analytical calls; root-reviewed
evidence, exact PR/merged-main CI and compatible migration/recovery release gate.
