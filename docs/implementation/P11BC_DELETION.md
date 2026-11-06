# P11b/c private deletion integration

This change prepares history deletion and account closure on schema 9. It is a
separate change from P11a exports. `PRIVATE_DATA_DELETE_ENABLED` defaults to
`false`. Source integration and isolated tests do not activate production.

## Acceptance and cleanup

The original transaction verifies the exact recent-auth proof, current session,
privacy epoch and history generation under the user lock. It commits an
immutable original intent, bounded original fingerprint manifest and temporary
job, and advances the history/privacy floors. Account scope also advances the
auth epoch and sets `status='deleting'`, immediately closing ordinary APIs.

The independent authority accepts the same original metadata under its physical
commit interlock. A successful HTTP acceptance requires its Ed25519-signed,
fsynced protected checkpoint header to be verified against the independent SQL
acknowledgement. Merely inserting an application job or independent SQL header
does not produce an accepted response. Failure after the local transaction
returns `503 retirement_pending`; the client reconciles the exact original
intent and never repeats mutation or proof verification automatically.

A dedicated worker resumes the immutable original manifest, at most one 128-entry
page per tick. Only `ConfirmedRetirement`, requiring a complete sealed original
fingerprint manifest and protected accepted header, permits physical purge.
Accepted and cleanup-complete are distinct states. Cleanup waits for actual
analysis-child, attachment-send and mail-sender lifetimes; lease expiry, a lost
DB session, a missing row or an expired public receipt cannot prove exit.

History scope purges only generations below its original floor. New history is
retained. Account scope purges every valid generation, all account-owned
workspace/auth data and associated private mail before removing the user.
Every database cleanup transaction has finite row/chunk limits. Private export
cleanup uses its existing chunk accounting. Workspace quota refunds accompany
each bounded removal. Permanent intent metadata has no user/job FK or expiry.

## HTTP contract

The existing preferences capability `private_data_delete` reflects the installed,
validated runtime and feature flag. No new account capability keys are added.

`POST /api/v1/me/data-deletions` requires exact JSON:

```json
{
  "intent_id": "canonical lowercase RFC 4122 UUIDv4 generated before recent authentication",
  "scope": "chat_history_v1",
  "proof_token": "v2. plus 43 Base64URL characters",
  "receipt_token": "a distinct v2. token generated from 32 random bytes",
  "confirmation": "DELETE HISTORY"
}
```

New deletion intents and their recent-auth proof targets require canonical lowercase
RFC 4122 UUIDv4. This constraint does not change the general retirement UUID
parser or purpose-only reconciliation of retained original intent records.

Account scope is `account_v1` with exact confirmation `DELETE ACCOUNT` and
recent-auth operation `account_delete`. History uses `history_delete`. Both
proof operations bind the exact intent UUID, scope, auth/session authority,
privacy epoch and history generation. Caller-selected owners, floors, expiry or
authority are rejected. A receipt must differ from the recent-auth proof.

`POST /api/v1/me/data-deletions/by-intent/{intent_id}` requires exact empty JSON,
`X-Aqua-Deletion-Receipt`, the original session cookie, paired `X-CSRF-Token` and
exact `Origin`. Receipts never enter URLs, logs, local/session storage or exports.
The purpose endpoint does not renew the session. It can acknowledge only the
original preaccepted intent, even after account closure revoked normal access.
It cannot create another intent, authenticate ordinary APIs or return private
content. Its complete SHA256 ticket digest and original cookie digest are checked
with constant-time comparisons. The signed job UUID commits that exact context
using a separate HMAC domain. Receipt expiry is fixed at original creation plus
at most 600 seconds, further limited by the original session absolute expiry.

Responses have this closed projection:

```json
{
  "schemaVersion": 1,
  "user_id": "captured canonical owner UUID",
  "job": {
    "id": "original job UUID",
    "intent_id": "original intent UUID",
    "scope": "chat_history_v1",
    "state": "accepted",
    "accepted": true,
    "cleanup_complete": false,
    "created_at": "original UTC timestamp",
    "receipt_expires_at": "fixed original UTC timestamp"
  },
  "history_revision": "opaque owner-bound generation revision"
}
```

States are `awaiting_authority`, `accepted`, `purging`, `complete`. New accepted
creation returns 202; an exact accepted create replay may return 200. Receipt
reconciliation returns 200 and may explicitly report awaiting/accepted=false.
Only 202 with a strict matching accepted DTO is the initial accepted signal;
there is no separate HTTP cryptographic acceptance header. The protected signed
header is verified privately on the server. An unavailable authority after
acceptance returns 503. Missing, expired, revoked or purged metadata returns 404
and never implies successful physical cleanup. Unfinished jobs outlive their
public receipt/window until cleanup actually settles.

Receipt status access lasts at most ten minutes and remains bound to its originating
session. This differs from the job's one-hour expiry. Expired completed job records
may remain until bounded worker cleanup removes them; expiry does not confirm
physical cleanup or promise immediate erasure. Limited security budgets and
retained deletion metadata may remain after the requested saved content is removed.

## Generation fence and grants

`X-Aqua-History-Revision` is an opaque owner/generation HMAC on authenticated
responses and Google/password login. For generations above 1, workspace/query
mutations require the captured matching revision. Old tabs, held requests and
late answers cannot adopt a newer revision or resubmit old prompt bodies. A 409
clears old private state and triggers explicit reload. Logout and cancellation
retain their original authority semantics. Every analysis job and export
snapshot binds or filters the current generation; late old workers cannot
commit into the new history.

Account manifests capture all known active/inactive Google subjects, verified
mailboxes, provider observations and historical grant evidence. The independent
store keeps HMAC commitments, including an installation-wide reserved dataset
namespace, so later configuration changes cannot reseed legacy subject/mailbox
approval. Google automatic grants remain behind the independent physical gate
through the app COMMIT. A new account may have a fresh UUID and no old history;
the retired identity cannot automatically regain analytical grants. Fresh
explicit operator decisions remain separate. Turning new deletions off never
disables an installed retirement grant/restore gate.

## Independent installation and recovery

The separate `aqua_retirement` logical DB has execute-only writer, checkpoint
and recovery roles, each limited to one connection; the DB cap is 4. No app role
can connect to or modify its tables. The normal backend receives the identity
HMAC key, public verification key and protected checkpoint file read-only. It
never receives the private signing key or recovery credentials. The reviewed
single-process topology has app web 4, export worker 1, download 2, deletion worker 1
and mail worker 1 slots: 9 app-runtime connections, below the role cap 12. The
independent role connections are inventoried separately.

Normal startup verifies the complete protected chain against the independent
authority head, reconciles exact known pending local acknowledgements, and checks
local sequence continuity, the latest digest and user retirement floors. These
checks rely on reviewed insertion/confirmation paths, immutable existing originals
and trusted whole-backup provenance. Startup does not independently reauthenticate
every previously acknowledged local original. A normal crash may fill a missing
local ACK for the same original intent and resume its original manifest. Missing
independent events, mismatched checked metadata, rewound floors or missing protected
authority keep all private API writers closed. Cheap liveness remains separate
from readiness. Offline recovery additionally authenticates each independent
original event and its sealed fingerprint pages before private access resumes.

`retirement.recovery.reconcile` is an offline operator API, never an HTTP route.
The operator must first stop and prove exit of all old backend processes, apply
the existing owner restore-session fence and keep writers closed. The recovery
role streams 128 events and four fingerprint pages per read, verifies the entire
PostgreSQL binary event chain against the signed protected head, checks every
sealed original manifest and restores only those original floor/closure facts.
It persistently sets `recovery_required` and revokes restored metadata receipts.
Bounded physical cleanup must settle before recovery clears that marker. Old
physical analysis evidence is retained until actual supervisor/host exit proof;
its age cannot clear it.

An accepted staging header with a missing immutable original manifest cannot be
replaced by a smaller enumeration from an older backup. Recovery stays in
maintenance until the exact original is recovered and sealed. An interrupted
recovery is idempotent and does not consume a proof or invent a new floor/job.
The schema9 runtime and retirement enforcement must remain in place for rollback;
the historical schema8 export image cannot enforce deletion or serve schema9.

The authority and protected chain must survive **every still-restorable legacy
application backup**, including manually retained copies. Existing backups have
30-day configured retention but pruning is disabled. There is no 30-day intent,
fingerprint or checkpoint expiry. A logical DB in the same cluster alone is not
an independent disaster-recovery copy; separately protected copy/recovery proof
is an activation prerequisite.

## Physical mail contract and release prerequisites

The host launcher retains its existing exclusive singleton lock and additionally
holds a shared lock on a distinct owner-only zero-byte physical lock before
creating its worker. The actual mail worker receives that same inode as a
read-only bind at `/run/aqua-mail-physical/worker.lock`, with
`ACCOUNT_MAIL_RETIREMENT_LOCK_ENABLED=true`, and holds its own shared descriptor
through synchronous send and final commit. The web runtime receives the same
inode read-only at `/run/aqua-retirement/mail-worker.lock` and must acquire an
exclusive lock through account-purge COMMIT. Thus a live sender still blocks
cleanup if its DB session or launcher dies. A missing/writable/wrong-owner/link
or incompatible mount fails closed. No mail key or private mail configuration
is mounted into the web container for this purpose.

The launcher generates reserved decimal `ACCOUNT_MAIL_PHYSICAL_DEVICE` and
`ACCOUNT_MAIL_PHYSICAL_INODE` from its held descriptor; they cannot come from
`worker.env`. The worker checks those exact values and the named inode before
returning a live process-local host-claim object. The mail outbox checks that
claim on its existing single DB connection before claim/send. An independent
`aqua_retirement` database in the cluster or the one-way app
`authority_installed` marker makes that claim compulsory even if the environment
flag is omitted or false. The catalog check survives an app-only restore that
rewinds the old marker. Missing retirement configuration cannot reopen an
installed web backend. Legacy mail behavior remains available on a genuinely
uninstalled schema9 fixture/site.

Activation remains blocked until fresh source-bound backend/frontend/browser,
schema8-to9 upgrade/rollback, independent SQL/privilege and full app-only restore
rehearsals pass; exact one-process/mount/physical-inode and app/retirement pool
inventory is proven; real append-only checkpoint storage and durable publisher
recovery are proven; separately protected authority/key retention and historical
backup recovery are demonstrated; and the normal release/security review passes.
Synthetic authority responses test application boundaries and cannot prove real
checkpoint fsync, signing, append-only storage or production readiness.

## Reproducible isolated checks

`python tools/checks/run_retirement_integration.py` performs no Docker actions.
Add `--execute --image aqua-checks:p00` to run the current schema9 app and
independent databases on a run-owned private Unix socket. The fixture uses the
real `AuthorityClient`, `Broker`, SQL and Ed25519 publisher with actual fixed-size
writes/fsync. It exercises unpublished acceptance, history and account routes,
complete manifest seal/purge, forbidden role privileges, new-UUID grant denial,
an actual app-only pg_dump/restore with signed authority retained, offline
reconciliation and signature tamper rejection. Its synthetic dump remains only
in RAM; the report records its hash and exact resource cleanup.

That fixture explicitly reports `append_only_inode_storage_proven=false` and
`physical_mail_mount_proven=false`; its unprivileged tmpfs cannot prove those
operator gates. It does not use `SyntheticAuthority`. Dedicated API/proof and
restore regressions separately use explicit fakes for fault/race boundaries.
`run_backend.py` collects the entire backend suite, proves four disjoint fresh
batches cover every collected case, merges actual JUnit and retains the original
dedicated export-capacity case. This limits disposable database WAL growth from
repeated migrations without dropping cases or changing resource caps.
