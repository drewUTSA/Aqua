# P11 progress

The exact `73270e4` run `43480716759` reached the workflow's 20-minute outer
job limit during the final Legacy Settings browser gate; its eight other jobs
passed. The preceding all-green `44c481d` checks job took 19m44s. The outer
checks-job allowance is now 30 minutes to accommodate this retained sequential
suite and hosted-runner variation. No test is removed, assertion changed,
application deadline extended or child/container resource budget increased.
Fresh complete CI on the resulting head is still required before merge.

**Latest November 13 checkpoint:** All nine jobs in run `43476718496` passed
on `44c481d`, including the original 48 publisher controls and full disposable
backend/database matrix. Tailscale and key-only SSH are now verified from the
office PC; read-only production readiness confirms schema8 and the exact P11a
images. The source-bound native image below passed the actual kernel/inode
durability gate with no production input or change and confirmed scoped cleanup.
Ben directed backup-key discovery and final backup/recovery execution to his
personal computer. See [the release handoff](PERSONAL_COMPUTER_RELEASE_HANDOFF.md).

The new native image is
`sha256:3ee8441fd77cfec284e748dc83067d3bb760db9895268cc354188d5c387e95d6`.
Its 194 application inputs match the existing reviewed source; the sole runtime
input delta is the patched dependency lock. The native rehearsal profiles now
bind that image and the actual 195-file metadata inventory, with an added pure
source/lock coherence guard. See [runtime inventory](evidence/p11bc/resume-20261113/runtime-inventory.json)
and [actual host durability](evidence/p11bc/resume-20261113/host-durability.json).
The refreshed actual installer/genesis/export/recovery-CLI rehearsal and ordinary
compiled-runtime rehearsal now pass on `73270e4` with strict cleanup. The latter
proved flag-off accepted purge, closed restored-history startup, retained-authority
recovery and readiness without injecting a runtime factory. See
[installer receipt](evidence/p11bc/resume-20261113/installer.json) and
[ordinary-runtime receipt](evidence/p11bc/resume-20261113/normal-runtime.json).
These do not prove independent encrypted retention or total-host recovery.
Exact latest PR/main CI remains required. Production schema9 installation/activation remains pending the
personal-computer recovery/backup gate; no later step below supersedes it.

## November 13 resumption — publisher measurement repair

PR #58 at `1c2d99e` passed eight browser jobs but its main checks job failed in
the native 48-case publisher signal suite (run `42182127124`). The original
idle assertion was reproduced with a monotonic start of `127.00000001`:
an unchanged 50-second deadline subtraction produces `50.000000000000014`.
Actual cleanup succeeded, but the exact measurement assertion failed.

The child adapter now removes only one representable clock unit of subtraction
roundoff. The original 48 case bodies, assertions, production launcher/deadlines,
resource caps and external-signal requirements remain unchanged. The immutable
original fixture copies remain untouched. AST reversal checks account for the
two measurement calls and the small helper, in addition to the existing scope
adapter. Three new guards cover clock boundaries, genuine changed budgets and
actual child execution against the original assertions. All 12 pure signal
guards pass locally. All 513 Python files pass Black and Ruff passes.

The Windows checkout had converted hash-pinned files to CRLF. `.gitattributes`
now fixes text checkout to LF while leaving detected binary assets unchanged;
the private task worktree was restored to committed LF bytes. No pinned source
hash is weakened to accept arbitrary newline variants.

Fresh Linux CI is required for the original 48 controls and all release checks.
Local Docker startup failed because WSL is not installed. The native executor
guard run also encountered unsupported Windows symlink/geteuid/pipe-selector
operations; that run is blocked, not a passing Linux qualification. No test was
removed or skipped to hide those setup errors. No production operation ran.

The documents identify SSH `ben2004@192.168.1.200`; that address timed out from
this PC. A dedicated owner-only client key and strict-host-checking `aqua-codex`
configuration were prepared outside the repository. Host routing, server-side
key installation and independently verified host identity remain pending.

The historical checkpoints below describe earlier source/evidence.

The first resumed CI run `43475785176` stopped at dependency audit before the
signal suite: `opentelemetry-api==1.45.1` is now flagged for CVE-2026-126360.
The runtime pin is updated to 1.45.2 with both exact PyPI artifact hashes and a
matching direct security floor. The local audit now reports no known
vulnerabilities; the existing real propagation oversized-header denial,
exact-boundary and normal-recovery probe passes on 1.45.2, and pip check passes
for that supplementary local installation. Full Linux runtime/image and
dependency validation still belongs to the fresh CI candidate.

P11a exports are deployed and enabled on schema 8 from PR57/main `9aeaf4e`.
The guarded release passed at 2026-11-06T01:00:49Z after a fresh authenticated
encrypted stopped-writer backup. Phase11 remains active: deletion is not deployed.
Public audience and analytical grants are unchanged.

## P11a exports: released and verified

The November 5 native Linux candidate passed all 25 gates and 1,680 backend
case identities across both datasets, retaining all 1,635 prior cases. All
eight core batch restores and both bounded-capacity checks passed. Installed
runtime bytes match the reviewed 167-file package. The frontend passes all
564 units, retaining every prior 528 test occurrence, with both builds and
bundle checks passing over 279 inputs.

All 58 browser gates passed across Opal and Legacy. Root reviewed all 200
screenshots and eight full-resolution export details. The compatible fallback
passed 23 fresh native gates, 1,651 cases, both restores and 35-table
clone/startup preservation, plus all 42 browser gates and root review of 162
screenshots. Eight full-resolution actual unlink images cover both candidate
and fallback, closing the inherited screenshot-label gap.

Browser fixtures ran on pinned Mac ARM images. Their native AMD64 targets
are qualified by equality of all normalized runtime files, lock, all 50
installed distribution versions/dependency declarations and runtime metadata,
together with direct native backend/restore/clone checks. Binary identity and
direct native execution of those browser journeys are not claimed. The Mac
Escape adapter changes only an optional native key field; original assertions,
timers, resource ceilings and genuine cooldowns remain.

The isolated schema-8 catalog, all ten original migration/recovery rehearsal
checks and original nine-report fallback validator passed. Only three rehearsal
lineage constants changed to bind the fresh fallback; SQL programs, assertions
and deadlines are unchanged. Both native frontend images contain the exact
tested artifacts and pass the bounded proxy checks.

Both exact hosted runs passed all seven jobs/170 steps: PR42106746185 on
`895f287` and merged-main42109731617 on `9aeaf4e`. All13 native operator
guards passed. The real release preserved protected rows, database identity,
volumes, mail-worker configuration and scheduler. Only
`PRIVATE_DATA_EXPORT_ENABLED` changed. One web process uses8 planned runtime
connections with2 probe slots within the12-connection role limit.

The strict preflight caught vendor nginx environment drift in the first static
image. The final package keeps the pinned deployed nginx runtime and the exact
same8 tested assets/configuration; no JavaScript was rebuilt. Both final native
images passed the original120-request/40.65-second proxy exercise and separate
23-request export probes, with strict cleanup. Public assets match origin;
the sole Cloudflare analytics-beacon transform is independently pinned. The
site and health return200; unauthenticated protected routes return401 and
private readiness remains404. No authenticated/provider/analytical smoke ran.
See [verification.json](evidence/p11a/verification.json) and
[release.json](evidence/p11a/release.json). Prior failed evidence remains retained.

## P11b/c deletion: integrated, host activation work remains

Deletion is implemented on a separate branch. The independent retirement
authority requires protected signed acceptance, immutable intent replay,
complete fingerprint manifests before purge, generation fencing and bounded
physical cleanup. A purpose-only, memory-held receipt supports reconciliation
after account sessions are revoked or a successful creation response is lost.

The final backend matrix passed all 1,851 unique case identities across both
synthetic datasets, retaining every prior 1,810 case and adding 26 contract and
15 legacy-housekeeping regressions. Every case passes on at least one dataset;
all 41 new cases pass on both. All eight full application dump/restore batches
and both real 32 MiB capacity checks passed within the original resource limits.
The full dump/restore reports do not enumerate a separate 39-table comparator.
The original 80 protocol guards pass on native Linux without skips after a
reviewed stdin harness fix; the initial red is retained.

ROOT reviewed and integrated the narrow cross-language contract fixes: new
deletion intents and proof targets now match the existing JS UUIDv4 boundary,
while retained reconciliation readers and general retirement UUID parsing stay
unchanged. The response formatter requires literal, consistent acceptance and
cleanup booleans. Real PostgreSQL red/green checks also confirmed and fixed a
legacy housekeeping path that could remove non-null physical-lifetime markers.
The fix preserves those markers until actual exit proof, without changing P07
caps, admission or quiescence limits. No late-write resurrection was demonstrated.

The final ARM backend package contains all 195 reviewed runtime files, with
exact source hashes, ownership and modes. It retains the tested dependencies,
image configuration and original filesystem layers; pip check passes. Its
immutable ID is `sha256:55227ce9093383a0687659b6fdf26a7881c2c9be022e0354c5c2447c55243e23`.
Native AMD64 packaging also passed on immutable
`sha256:aba612fc0f6368a6dbf7c40ceddf06de8c3b87a31c00863c7fc528762ad8eeb5`.
It preserves all 195 bytes/owners, complete image configuration, base layers and
all 50 distribution metadata records. Common source modes tighten from 0664 to
0644; no executable bits change. Both pip checks exit successfully; the exact
read-only cache warning is retained. Native execution of all 1,851 case identities also passed on that immutable image,
including all eight restore batches and both capacity cases. Every prior 1,810
case is retained and the 41 new cases pass on both datasets. ROOT independently
verified the actual JUnit identity sets and pass union. Actual ordinary startup
and flag-off fallback qualification now pass in all three modes. Accepted receipt
and background purge continue with new creation off; an unsafe restored state
exits ASGI startup closed with no listener/private admission; after actual
retained-authority repair, ordinary startup is ready, a distinct UUID has no old
grant, capability is false and new deletion returns503. No ordinary runtime is
injected. See [normal-qualification.json](evidence/p11bc/normal-qualification.json). Earlier source-bound fixture reds remain retained and their final
JSONDecodeError cause remains unproved; no speculative application fix is claimed. See [backend-runtime.json](evidence/p11bc/backend-runtime.json)
for the reviewed source, runtime, dependency and two-architecture matrix receipts.

The final wording-bound frontend passes all 600 units, both compact builds and
bundle limits, all 58 original browser cases, both signed two-database journeys
with seven checks each, and the separate six-case synthetic deletion fixture.
No retry or assertion/resource relaxation was used. ROOT reviewed all 203 fresh
screenshots through 11 contact boards and eight critical full-resolution images,
including both actual account-completion receipts. This count comprises 200
matrix screenshots, two signed-flow screenshots and one standalone screenshot.
No new P11 visual blocker was identified. These Mac ARM browser fixtures retain
their explicit synthetic provider/physical-boundary limitations; ordinary normal
Uvicorn startup remains a separate native gate. The frozen 298 frontend files,
14 built assets and 195 runtime files are pinned; later unused CI-helper changes
are recorded separately rather than claimed identical to that full source archive.

The unchanged 600,000-byte login gate had caught an eager deletion-review bundle.
Explicit-review code now loads when requested, with receipt/privacy fencing in
the parent. Final Opal/Legacy login assets are 597,850/597,852 bytes. Current-run
containers, volumes, profiles and process groups were removed. An unrelated old
profile predating this run was left untouched; no global temporary-folder cleanup
is claimed. Both native frontend packages now preserve the deployed nginx image
configuration and base layers and contain all 14 exact tested assets. Opal and
Legacy each passed the original 120-request proxy exercise and separate
23-request export probe on their first attempt, within unchanged limits. All
eight owned test containers are absent and live service metadata is unchanged.
See [frontend-qualification.json](evidence/p11bc/frontend-qualification.json).

Anakin independently passed 600 units across 48 files and six Chrome synthetic
journeys. It also passed six Edge journeys and a fresh six-case Edge run against
the reviewed cleanup runner on its first attempt. The runner now reports success
only after cleanup; native Windows checks confirm process, listener and profile
absence. The original inconclusive Chrome cleanup probe remains beside its
independent successful cleanup check. Windows component fixtures do not prove
PostgreSQL locking, physical purge or production readiness. ROOT reviewed the
copy changes clarifying export exclusions, requested-content completion, retained
metadata and ten-minute receipt access. Export schema and behavior are unchanged.
See `evidence/p11bc/windows-verification.json` for the earlier frozen Windows set;
new raw receipts remain in the coordination evidence pending final curation.

Actual Linux v4 host composition passed real append-only inode checks, signed
acceptance, pre-ACK SQL failure/retry, seal/purge, app-only restore, grant denial
and poisoned-tail rejection, plus four separate real MailWorker lifetime checks.
No synthetic ioctl or mail-mount seam is used in that native proof. The initializer
exits before flag-setting and a new capability-free signer starts afterward;
APPEND does not revoke writable descriptors opened before the flag. This proof
binds its historical frozen source; final runtime qualification remains separate.

The authority bridge passed actual synthetic age encryption/decryption and
rejected damaged ciphertext. Its concrete keyless SQL-restore verifier passed
42 pure guards and independent review. The final producer actually accepted
129 fingerprints in pages of 128 and one, independently read the signed head,
captured the full backup-role dump under the recovery gate, and passed archive
and cryptographic verification with complete owned-resource cleanup. Its
required isolated SQL restore challenge now passes after source-reviewed fixes.
The full dump restores in parent-before-child order under the same INSERT-only
role with all constraints active. Actual verification covers all six tables,
one signed event, both original pages, all129 fingerprints, floors, accounting,
SELECT-only privileges and connection limits. Psycopg startup errors may omit
SQLSTATE: the role-limit proof requires the exact role-specific FATAL while the
first authenticated slot is held, actual limit1, and an identical-DSN successful
connection after release. Generic connection failure never passes. Actual age
encryption/authenticated RAM decryption and complete archive/chain/key checks
passed; source/probe resources were independently confirmed absent. The cipher
and separate QA age identity remain in private Mac storage. This synthetic actor
proof does not substitute for the create-only Scope installer/export/recovery
CLI rehearsal or a production backup. Prior reds remain retained. See
[recovery-verification.json](evidence/p11bc/recovery-verification.json).
Earlier producer rehearsals exposed fixture issues:
Docker's legitimate newline-only missing-object output was rejected, then the
preparation timer conflicted with the production capture deadline. Both reds are
retained; scoped inspection confirmed absence after the first and full cleanup
passed after the second. Neither reached a dump or SQL verifier. Narrow fixture
corrections preserve production guards and aggregate execution limits. The complete create-only installer/held head and full five-member RAM export/
genesis app-only recovery CLI rehearsal now passes on the exact native image.
Actual HBA password/authority-role denials, signed genesis, APPEND lifecycle,
keeper release and all exact resource/root/volume cleanup passed. This genesis
CLI proof is separate from normal-factory accepted-data repair and synthetic129
encrypted SQL recovery. Final integrated nine-job CI, fresh production backup/
retention and the guarded schema9 production deployment remain activation gates. Total-host recovery stays closed without an independently
verified latest accepted head and complete ledger/key coverage; backup age alone
cannot establish this. No production authority, new authority keys, schema9
migration or deletion activation is claimed. Failed evidence is retained.

## Recovery and retained failed attempts

The operator approved a new recovery-key copy in private, unshared Google Drive.
Owner-only permissions were checked before and after upload. A downloaded copy
matched the local key and decrypted a fresh challenge; controller preflight
passed. The fresh stopped-writer application backup also passed during the P11a release.
This does not establish deletion-authority or total-host recovery. The new key does not recover older backups encrypted with an
unavailable prior key.

Backup retention remains 30 days with automatic pruning disabled. Existing
backups may remain longer; retirement protection must cover every restorable
copy. The 24-hour RPO/four-hour restoration values remain targets. P12
measurements and P13 launch gates remain incomplete; public audience expansion
remains outside these preparations.

Retained failed attempts include catalog-tuple exhaustion in the unchanged
512 MiB fixture, two hosted whole-suite deadlines, Chrome startup failure,
Mac Escape transport diagnosis and the deletion bundle limit. The isolated
database fixtures now use one-second autovacuum without raising resource or
execution caps. The complete suite runs in four fixed sequential module batches
per dataset, with exact disjoint JUnit identities, fresh same-capped fixtures
and the original 120-second execution limit per batch. Failed attempts cannot
satisfy current gates.


## Final integration qualification, November 6

ROOT integrated the reviewed installer, ordinary-runtime and capture helpers plus
the durable Mac backup client. The final five closed Linux suites passed all258
cases: protocol80, archival9, operator77, fixtures36 and backup models56. All five
containers passed ID/name cleanup; independent name absence and unchanged existing
running metadata were confirmed. All534 frozen public source inputs matched
the checkout at that qualification. Later exact helper exceptions are documented
below. See [native guard qualification](evidence/p11bc/native-guards-qualification.json).

Fresh probes of the exact final ARM and AMD64 backend images measured all50
package versions and complete Requires metadata, Python, OpenSSL, libc and the
OS-release digest. The package closures and software metadata match; both probes
exited cleanly and their exact resources were removed. These metadata checks
complement the separate195-file runtime proof. See
[architecture qualification](evidence/p11bc/architecture-qualification.json).

The full create-only installer/held keeper/export/genesis recovery CLI proof is
recorded in [installer qualification](evidence/p11bc/installer-qualification.json).
It does not claim accepted-data recovery, encrypted retention or total-host
recovery; their separate evidence and restrictions still apply.

Anakin's approved Chrome rerun passed all six original synthetic assertions after
a one-line expiry-fixture readiness fix. The harness now waits for authenticated
status before clicking the history button. Its deadlines and assertions remain
unchanged;297 other frontend inputs match the frozen final source. The previous
failed Chrome and Edge runs remain retained. This Windows runner used its sealed
1536 MiB cap; older1024 MiB Edge evidence remains separate. See
[Chrome readiness evidence](evidence/p11bc/windows-chrome-readiness.json).

Black checked506 Python files unchanged; Ruff, source checks and runtime-lock
checks passed. The final integrated nine-job PR/main CI and actual guarded
production schema9 release remain incomplete. Production stays on the healthy
schema8 export release while concrete release controllers undergo ROOT review.


The first published nine-job candidate, `f09a76b`, passed eight jobs and the
complete backend step (all1851 identities plus both current32MiB capacity cases).
Its later storage-installer step correctly failed because the host helper still
expected schema8 after the actual schema9 migration. ROOT changed only the
expected output literal and returned version in `ops/appdb/manage.py`; no runtime,
case, migration or resource limit changed. PR58 run42168334557 then passed all
nine jobs/210steps on `75432178cd396297191183d89afb468ef0d05a56`, including the
real disposable repeated migration, authentication/DDL denial, full RAM export
and cleanup checks. The earlier red remains retained.

The main merge also contributed only two PG command arguments to the capacity
fixture (`-c autovacuum_naptime=1s`). Both current-source capacity cases passed
in the actual hosted backend step with schema9, original32MiB/1GiB/512MiB
limits and exact cleanup. These two narrow host-helper/fixture exceptions are
separately hash-bound; the historical frozen source archives are not relabeled.

The current PR is held for the reviewed installed-publisher cancellation fix
and final release/recovery controller review. The final source head and distinct
merged-main nine-job CI must still pass before activation. Production is unchanged.


The assembled migration snapshot guard now passes an actual isolated schema8→9
rehearsal. All35 old tables were populated; their hashes, roles, ACLs and old
catalog remained intact, all39 resulting tables matched the independent pristine
schema9 catalog, and the seven new defaults preserved the existing privacy epoch.
All10 actual checks and16 pure guards passed, including expired non-null physical
markers, export-work admission, old-row/catalog/privilege drift, and a32MiB pending
manifest rejected before payload traversal. Original caps remain unchanged.
ROOT rehashed the four raw artifacts and independently confirmed all four exact
container names and the run label absent. See
[migration qualification](evidence/p11bc/migration-qualification.json). This proves
the migration/snapshot component; the production256MiB snapshot profile and the
full rollout/rebind/recovery controller remain separate pending qualifications.
Earlier fixture failures remain retained; the source-copy failure's historical
683-byte message was not retained, so no exact retrospective cause is claimed.


ROOT reviewed and integrated the installed-publisher deferred cancellation fix,
explicit validated Scope routing, and the maintenance probe shared deadline.
The35 focused checks passed. The current native Linux signals suite passed all48
original controls, including six actual POSIX deliveries, under the unchanged
128MiB/oneCPU/64PID/60second profile. ROOT verified all539 frozen public source
files, both raw report/log hashes, exact temporary-container name absence and
unchanged running production metadata. The control cases model private I/O and
Docker RPC; the separate real installed-publisher/recovery rehearsal remains
pending. See [publisher signal qualification](evidence/p11bc/publisher-signals-qualification.json).
Black checked513 Python files unchanged; Ruff, source/lock checks, the18 native
executor guards and17 durability/host/cleanup guards passed. The added CI selector
retains all five prior suites and adds only its fixed report to artifact upload.
The current integrated source still needs final nine-job PR/main CI and release.


Candidate `a117cc9` / run `42177549158` retained two CI reds: the 77-case operator
model's one-argument stub rejected the valid existing maximum argument, and
the 80-case launcher model's dynamic importer omitted the real Scope dependency
path, collecting 74 rather than 80 cases. ROOT corrected only these two test
fixtures: the stub now also asserts the original 16,384-byte bound, and the
loader uses the actual ops source directory. No production code or assertion
was relaxed. Fresh native 77/77 and 80/80 passed at original limits with strict
cleanup, independently confirmed exact name absence and unchanged running
production metadata. The historical 539-file signal snapshot now has these two
explicit unused-test deltas; its actual signal/executor/control inputs are
unchanged. See [model correction evidence](evidence/p11bc/native-guard-model-corrections.json).


Run `42179270467` on `46a8900` retained two different CI failures. Legacy
identity notices timed out at Chrome startup (`Browser.getVersion`, 30 seconds,
zero page checks); scoped cleanup passed. The new signal suite failed with
`JSONDecodeError` in the outer result parser; the original inner log was not
uploaded, so its exact child failure remains unproven. ROOT added a bounded
public diagnostic projection containing only fixed case IDs/categories, hashes
and numeric facts to the already retained signal report. Raw child output and
artifact paths remain excluded. Independent review prompted an additional
malformed-row guard. All nine diagnostic/model guards and 18 native executor
guards pass; a fresh current-source native 48/48 run, including six actual POSIX
deliveries, passed at unchanged limits with strict cleanup and independent
absence. Original case bodies, assertions and deadlines are unchanged. See
[signal diagnostics](evidence/p11bc/publisher-signal-diagnostics.json).
