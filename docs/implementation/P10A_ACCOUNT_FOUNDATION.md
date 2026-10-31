# P10a account foundation

This separate slice adds profile editing and read-only method/session reviews
after the P09 homepage change. P10 remains incomplete. Candidate verification
uses disposable private databases, fake providers/mail and bounded browsers;
the separate verified release below records the production migration and backup,
without a real provider/mailbox test or a production restore claim.
Shared/Tiger databases, signup policy and analytical grants are outside this change.

## Supported contract

All routes require a current canonical account session, including accounts with
no analytical dataset grant. They derive ownership from the session, reject all
query arguments and return private `no-store` responses. Unsafe requests use the
existing exact Origin/session CSRF checks. Reads and failed profile CAS writes
share the durable workspace budget of 60/account/minute across cookies/workers.
GETs do not update session activity, idle expiry or authenticated freshness.

| Route | Closed request and result |
| --- | --- |
| `GET /api/v1/me` | `{schemaVersion:1,revision,user:{id,name,picture,email},email_verified:true,capabilities}`. `email` is the verified app primary, never a pending/provider-observed address. Picture is restricted to the existing safe Google image policy. |
| `PATCH /api/v1/me` | Only `{expectedRevision,display_name}`. Exact integer revision from 1 through JavaScript's safe integer maximum. NFC single-line plain text, trimmed, 1–120 code points and at most 512 UTF-8 bytes; control, format, surrogate and other Unicode category-C values are rejected. A valid stale revision returns 409. Same name with current revision returns the current snapshot without advancing it. |
| `GET /api/v1/me/methods` | `{schemaVersion:1,password:{linked,available,changed_at},google:{linked,available,identities:[{id,linked_at}]},capabilities}`. Availability reflects existing password feature flag/provider configuration; no provider subject, observed email, hash, raw claims or secret is returned. At most 20 active Google identities; fail closed on unexpected excess. |
| `GET /api/v1/me/sessions` | `{schemaVersion:1,items:[{id,method,device_label,created_at,authenticated_at,last_activity_at,idle_expires_at,absolute_expires_at,current}],capabilities:{revoke_one:false,revoke_all:false}}`. Current-epoch, live, unrevoked owned sessions only, at most 20. Current first, then activity. Unknown/untrusted device labels use `Unknown device`; no location inference, raw UA, CSRF or digest is exposed. |

Only `profile_edit`, `method_list` and `session_list` capabilities are true. All
recent-proof, password, verified-email, link/unlink, revoke-one/all and notice
capabilities remain false. P09's broad `account_security` preference capability
stays false and no frontend operation is connected by this slice. No future
sensitive mutation or proof-verification route is mounted.

Bodies are capped before parsing (16KiB for the new profile PATCH), JSON content
type is required, and duplicate object keys including escaped duplicates are
rejected. The existing preference limit remains 64KiB. Fixed private error
envelopes contain only code, safe message and request ID. Validation errors do
not reflect profile, proof or credential inputs. The existing private access-log
filter now covers the entire `/api/v1/me` namespace.

## Identity and primary-mail authority

Google seeds display metadata and the app primary only when a canonical account
is created. A returning active issuer/subject retains its canonical app profile,
picture, profile revision and verified app primary. Provider email changes are
stored only in the existing observed-email fields, even if that observed address
is now another account's app primary. New unknown subjects still cannot claim an
existing address or automatically merge/link accounts. This intentionally changes
the old returning-login overwrite behavior; existing password login/recovery
continues to use the app primary.

Inactive identity tombstones are represented but no unlink route is enabled.
Resolution and final session insertion each check the exact identity's active
state, with the final check under the user lock to close the transaction gap.
Legacy-derived grant seeding and evaluation require an active identity; operator
grants remain independent. This slice performs no grant/consent mutation. Future
unlink must preserve provenance/FKs, revoke all sessions/advance epoch and handle
derived grants atomically before it can be enabled.

## Recent-proof foundations that remain internal

The finite operations are email_change, password_change, google_link,
google_unlink, session_revoke and sessions_revoke_all. Targets are canonical,
domain-separated SHA-256 bindings computed by server code; no API accepts a
caller-chosen owner or target digest. Owned identity/session targets are checked
before any future verifier work.

Challenge creation and every claim attempt each commit the existing durable auth
admission implementation in a separate transaction: default 5/account/minute and
30/global/minute in distinct action scopes, independent of login/recovery scopes.
Denied target/claim work does not refund admission. Policy is server-owned and
bounded; browser preferences cannot set it. At most 5 retained challenges/account
and 1024 total are admitted, with bounded expiry cleanup and no live tombstone
eviction. Challenge lifetime and maximum future proof lifetime are 300 seconds.

Claim consumes an exact user/session/epoch/action/target/secret/browser-binding
challenge before any detached provider/Argon2 verification can occur. This file
does **not** implement that verification or a proof issuer. A later verifier must
use existing feature gates and durable hash slots, perform expensive work outside
DB leases, recheck the exact current credential/identity snapshot under the user
lock, and insert only a challenge-bound digest proof whose expiry also fits the
original challenge. An ordinary authenticated_at timestamp is not such proof.

`consume_proof` is an internal repository primitive for the same transaction as a
future mutation. It rechecks current user/session/epoch/action/target, unexpired
claimed challenge, unexpired unused proof, and current active Google identity or
unchanged password timestamp. Lock order is user → session → challenge → proof,
matching challenge cleanup before its cascading proof delete. A failed mutation
rolls back consumption; replay and concurrent second consumption deny. There is
no general `mark_verified`/mint shortcut or HTTP route that could bypass a real
verifier. Sensitive changes will revoke all sessions in a later slice, not here.

## Migration, compatibility and rollback

`0006_account_security.sql` is the only new migration. Applied 0001–0005 remain
unchanged. It adds profile revision, inactive identity state/revision, complete
optional account bindings on existing reauth challenges, a digest-only proof
table with owner/session/challenge/identity FKs and finite method provenance,
appropriate partial/indexed lookups and the new durable admission scope values.
Existing legacy unbound challenges are preserved but cannot enter the new
protocol. Existing users, primaries, methods, preferences, provenance and grants
are neither re-created nor bulk-reassigned. Existing restricted runtime and
backup roles receive only the same explicit data access model; no DDL/owner or
analytical-reader permission is added.

Runtime readiness, installer and Python fixture probes require schema 6 together.
The restore fence conditionally consumes restored action proofs while preserving
older-schema backup compatibility. No ordinary startup invokes migrations.
Disposable migration/repeat/interruption/restore/role/index tests and the full
backend matrix remain required before an operator applies 0006.

The verified release advanced the private database from schema 5 to 6 and
started the matching P10a images. Do not bypass readiness to run the P09 image
on schema 6. The new
inactive state is all-active by default and no removal operation is enabled, but
P09 still has the old Google overwrite behavior. Prefer a compatible forward fix
with new capabilities disabled and data retained if a deployed P10a needs
recovery. Once any future unlink/security mutation activates, rollback must keep
enforcing tombstones and epoch/session revocation; old P09 auth is incompatible.

## Verification and activation prerequisites

The fresh canonical Linux run passed source/lock, Black/Ruff, runtime dependency
audit, all 1,440 unique backend cases across the two fixture datasets, exact byte
proof for 126 runtime files, privacy/telemetry, real synthetic dump/restore,
private storage installation and bounded proxy denial/recovery. All owned
resources were removed and the existing production containers stayed unchanged.
The candidate image is
`sha256:a3b2fd374ad987202d2c79b02df1517c702106c468e422c7128b86e30b2c0b43`.

New disposable tests cover profile CAS/Google preservation and provider-email
collision, missing/stale/revoked/disabled authority, CSRF and mass assignment,
ambiguous/deep/oversized JSON, shared durable admission, private non-extending
session reads, expired-history query plans, hard list caps, inactive identity
login/grant fences and final session race, schema 5→6 preservation, proof binding,
replay, wrong owner/session/action, expiry, method changes, transactional rollback
and cross-storage concurrent consumption. The actual restored clone preserves
profile revision, primary/credential metadata, active/inactive identity
provenance and preferences, while repeatedly fencing sessions, challenges and
action proofs. This is isolated recovery evidence, not a production restore.

The integrated frontend passed 455 unit tests, both production builds and a
fresh zero-finding runtime dependency audit. Account actions save independently
of presentation preferences. Both new real Account journeys passed 27 checks,
including CAS conflict review, a lost committed response reconciled by GET,
same-owner auth locking, native-modal suppression and exact held-read abort.
The eight existing workspace/Settings/Plotly gates also passed on the same
final assets: 136 synthetic, 43 real workspace, 41 Settings, 37 Plotly and 27
Account checks per shell, 568 total. All 234 frontend source/check inputs and
all nine static assets, including lazy Settings chunks, were bound to those
reports. Twenty-six current screenshots were reviewed. Required PR/main CI and
the private-schema release passed. Portable isolated evidence is in
`docs/implementation/evidence/p10a/verification.json`.

Nonroutine integration prerequisites:

- Fixture-only schema expectations are 6; preference schema remains 1. The
  bridge allows only exact current-owner GET/PATCH profile and GET method/session
  routes without query authority. It rejects foreign paths and future mutations.
  CI retains all eight existing gates and adds both Account journeys.
- The P10a release used a fresh authenticated encrypted schema-5 backup after
  writers stopped and the reviewed explicit migration/recovery procedure. Future
  private schema changes retain that gate. No shared/Tiger DDL was performed.
- Before future proof issuance, implement bounded password/Google verification,
  exact method-snapshot recheck, freshness/nonce policy and safe error handling.
- Before sensitive mutation, implement all-session revocation, last-method user
  locking, exact mailbox purposes/templates and notices as applicable. Never
  reuse anonymous enrollment/reset to add a method to an authenticated account.
- Notification scope remains generic optional in-app notices in a later slice;
  no optional email, browser permission, sound or fabricated delivery claims.

## Verified production release

[PR #54](https://github.com/drewUTSA/Aqua/pull/54) merged as `f5f5b2d16fab261173fd2572e620f266dc64168e`; both required CI runs passed.
At 2026-10-28T23:42:41.253826+00:00, the reviewed guard stopped writers and held the mail
worker lock, verified a fresh encrypted schema-5 backup and independent recovery
identity, applied only migration 0006, then started the exact tested backend and
frontend. Protected records, database/volumes, activation/environment, worker
file and scheduler were preserved. Public account APIs denied anonymous access;
all eight public/origin assets and healthy images were verified. The index HTML
difference remains the pinned pre-existing Cloudflare Analytics insertion.
The bounded public sign-in smoke passed; its screenshot was reviewed. The
Google control was loading at capture, so no real Google flow is claimed.

Encrypted backup SHA-256: `db21163455f2ba33f5c1ab1e10da78ada1160634ba80507a18cbf7248e313c02`. Authentication/decryption
matched the streamed export; no plaintext dump was written. This is backup
verification, not a production restore or an RPO/RTO guarantee. The ciphertext
and metadata were hash-verified in protected storage outside the checkout with
owner-only permissions; no credential copying or pruning occurred. No authenticated
production account, AI/analytical query, real mail recipient, public Google
audience or analytical grant was exercised or changed by release verification.
Exact portable evidence: [release.json](evidence/p10a/release.json). Schema 6
requires a compatible forward fix or maintenance; P09 image rollback remains
unsupported. P10a is deployed. P10b onward and the overall P10 checkpoint remain
outstanding.
