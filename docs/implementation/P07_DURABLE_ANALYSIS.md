# P07 durable analysis

Status: complete and deployed at code `1d08364` (PR #48), private schema 5.
Authorized October 26, 2026 by the user's request to proceed to P07, following
the completed activation/P06 run. Production cutover and public verification
completed October 27 UTC (October 26 local time). P08 onward remains excluded.

## Scope and contract

Preserve the P06 canonical chats/messages/request IDs and legacy `/api/query`
response. Add a private PostgreSQL lifecycle queue with bounded admission,
fenced leases, one total execution deadline, cancellation and safe progress.
Select follow-up context on the server before the new input's sequence; bound
its size and exclude prior result rows. Both UI shells use owned status and
metadata events, with polling fallback. Reconnection reads existing work.

The reviewed design uses two analysis slots, eight waiting requests,
one running/two waiting requests per owner and a 120-second intake-to-finish
deadline. Model fallback and repair share a four-call maximum. Dispatcher
children must terminate before their known slot is released. Normal cancellation
first interrupts the owned child so psycopg can cancel an active server query;
a bounded grace precedes forced termination. A forced stop retains conservative
capacity through the remote SQL bound; a locally unconfirmed exit quarantines
its slot until stopped-worker recovery. An expired running lease becomes
interrupted; reaching the intake deadline becomes expired. Both require an
explicit retry and are never silently sent to a provider again.

Admission reserves four possible provider calls per new logical request:
12 calls/minute per account, 120 globally/per dataset and 60 per configured
provider family. Unused attempts do not refund that window. Status/stream-open
reads have an independent 120/minute account/global budget, and cancellation
60/minute account/global. Replays and polling never create new model work.
Initial values are conservative policy, not a measured capacity claim.

New owned routes are `GET /api/v1/analysis-requests/{id}`, CSRF-protected
`POST /api/v1/analysis-requests/{id}/cancel`, and metadata-only
`GET /api/v1/analysis-requests/{id}/events`. Existing chat submission/retry
routes return a canonical 202 lifecycle snapshot. Current authority is checked
at admission, during work, at commit and on every status/event delivery.

P08 Plotly, P09 Settings, new data grants, shared analytical DDL, live provider
exercises and changes to the activated account-mail service are excluded.

Successful workspace results add version-1 provenance metadata. Source identity
is opaque, generation time is recorded, and unknown freshness, filters,
aggregation and units remain unknown. Exact sidecar cells preserve decimals or
large integers that the legacy JavaScript numeric representation would change.
The UI validates the sidecar, displays/exports exact strings, and withholds
lossy visuals with an explicit precision note. Legacy `/api/query` keeps its
existing final JSON shape. Limits are 64 columns, 1,000 rows, 1,024 exact cells,
256 characters per exact number, 160,000 metadata bytes and 240,000 bytes for
the whole normalized result. Plotly remains P08.

## Verification and release gates

Required: deterministic backend/lifecycle/real private-database tests, both
shells' unit and browser journeys, isolated red/blue lease/cancel/deadline,
queue/admission, legacy-bypass, context/cache and stream checks, formatting,
source/dependency checks, required PR/main CI, reviewed additive migration,
fresh encrypted backup, preserved data/volumes, actual-image proxy checks,
controlled production health/assets verification and worker resumption.

The serial browser bridge verifies real-database polling/cancellation;
progressive streaming requires separate genuine stream tests. Cancellation
cannot promise that a remote provider reverses work or charges already begun.

The frozen backend passed 229 distinct focused cases across both disposable
datasets, with an independent suite passing 63 cases in each: 37 adversarial
security cases and 26 focused API/cache regressions. The
frontend passed 236 unit cases and 103 synthetic browser checks in each shell.
Both shells also passed all 39 real private-database browser checks against the
final backend image and exact built assets, including server cancellation,
reconnect without new work, context, restart recovery and exact values. Browser,
profile and fixture cleanup passed. The test-only transport accounting bound is
512 browser requests; the separate opt-in bridge remains 400 operations within
300 seconds. Production quotas are unchanged by those fixture limits.
These browser results supplement the final-image database suite. Required PR/main
CI and production release gates passed separately. Credential-free evidence is retained in
[`evidence/p07`](evidence/p07/).

The final-image full matrix passed all 1,243 distinct tests: bank 1,224 passed
with 19 dataset-specific skips, Pagila 1,231 passed with 12. Every case passed
in at least one dataset. The schema-5 restore drill passed and exact fixture
resources were removed with absence confirmed. Each fixture run took about
50–52 seconds. The initial matrix caught 27 old test-fixture assumptions in each
dataset: insufficient waiter space for the new readers and process-local mocks
that cannot cross a subprocess boundary. Two test fixtures were corrected while
preserving real auth/CSRF/grant dependencies and all assertions. The full rerun
used the unchanged candidate image; independent subprocess/admission/security
integration cases remained real disposable-database tests.

The actual installer passed repeated schema-5 migration, password/role checks,
runtime DDL denial/recovery, memory-only synthetic export and owned cleanup.
Final source/lock checks, configured Black checks on 228 Python files and Ruff
checks on all 230 Python paths,
dependency audit, installed dependency consistency, telemetry denial/recovery,
private access-log protection and workflow lint passed. The isolated source
packet's missing unchanged `pg_hba.conf` was corrected before its successful
installer rehearsal; this packaging failure did not reach a database migration.
The existing Black configuration excludes `nl2sql/config.py` and `nl2sql/db.py`.
A separate read-only diagnostic found formatting-only differences in the latter;
it is not claimed as an additional passing Black gate. No runtime defect was
found, and the tested candidate source remains unchanged.

The first isolated proxy regression is now reproduced and fixed: the P06
configuration buffered both SSE frames until upstream completion. The P07
configuration delivered the first fixed metadata frame in 0.001 seconds while
the upstream completed in 1.002 seconds. The paired 116-request proxy run
passed shared submission limits, header/alias bypass denial, separate account
routes, progress/status/cancel access and normal recovery. Both runs used
network-none containers and fake loopback upstreams; exact resources were
removed and absence confirmed. These are proxy results, not backend lifecycle
or production stream evidence.

Both final frontend images also passed the complete 116-request proxy checks.
Their public assets and Nginx configuration matched the tested build files
exactly. The deployed backend is
`sha256:81acee49864b4c08ba400fdc41b512b03b3dcacdafc6c7df5dc8e990247845e7`.

| Image | Immutable image ID |
| --- | --- |
| Opal | `sha256:d86a8f577c7744ce85145e9359880618082deaa9eb7959250585a20efce73c9f` |
| Classic fallback | `sha256:5fcd5b541e37695427a8d07a7b2fd135dd9d497e63754954f92550af62118034` |

All 112 frozen runtime source/lock files matched their raw manifest. The 110
installed runtime assets matched the backend image with CRLF-to-LF as the only
permitted source comparison normalization. Frontend image checks compared the
complete public asset set and Nginx file exactly. No environment, key, database
dump or other private runtime directory was included in either build context.

## Operations and recovery

Migration 0005 is additive; migration files 0001–0004 remain unchanged. Its
schema-4 upgrade regression preserves history and interrupts any old pending
submission, refunding its reserved bytes exactly once. Restore fencing now
handles schemas 3, 4 and 5, invalidates old authority, interrupts unfinished
work, removes replay events/stream reservations and private execution payloads,
preserves completed history, and preserves spent admission budgets. Only use
that fence while every worker using the restored database is stopped.

The backend Compose service now has an init process, 3 GiB memory/swap ceiling,
four CPUs and 256 PIDs. Two bounded subprocesses run within that service;
there is no new infrastructure service. The isolated application database,
read-only socket mount and UID 1000 remain unchanged. Do not use `down -v`.

Before migration, stop the backend and pause the exact mail cron while holding
its launcher lock. Export a fresh authenticated encrypted backup with separately
protected recovery material, then verify the reviewed main commit and exact
tested image/source. Migrate with the existing reviewed installer and recreate
only backend/frontend without building or pulling. Verify schema 5, exact public
assets, private-route protections and unchanged activation flags, then restore
the hash-identical schedule and verify its next ordinary idle invocation.

After schema 5 is applied, the old schema-4 backend is not a supported rollback.
Use a forward fix or hold the web backend stopped while preserving data. The
tested classic frontend is a presentation fallback against the current backend.
On progress transport failure, authorized status polling reconciles existing
work without resubmitting it.

No live provider-quality benchmark, production load test, business database DDL,
new data entitlement or production restore is included. Conservative limits are
policy choices; measured capacity and agreed RPO/RTO remain later work.

## Completed production release

[PR #48](https://github.com/drewUTSA/Aqua/pull/48) merged only after the exact
reviewed head passed [PR run 40431771945](https://github.com/drewUTSA/Aqua/actions/runs/40431771945).
The merged code `1d083649322b26b13de76c148148a4ee00195480` then passed
[main run 40432773968](https://github.com/drewUTSA/Aqua/actions/runs/40432773968).
Both runs completed all 25 steps successfully, without failures or skipped steps.
An earlier PR run was superseded by a documentation-only clarification of the
configured formatting evidence; no runtime image changed.

The server checkout fast-forwarded to that reviewed commit. Preflight compared
all runtime source and the dependency lock to the tested image, resolved the
reviewed resource settings and verified no environment differences. Compose
serializes memory limits as numeric strings on this host; the operator preflight
was corrected to compare their exact numeric value. A disposable image rehearsal
also proved init, 3 GiB memory/swap, four CPUs and 256 PIDs, with confirmed cleanup.

The exact mail cron was paused and its launcher lock held through stopped-writer
backup and migration. Fresh encrypted schema-4 snapshot
`pre-p07-20261027T013844Z.pgdump.age` has encrypted SHA-256
`e65dd757d0755e913abdf7637f1df606f53de12e946b418847fc8de11236b646`.
The same stopped backend and live guard were attested before export and after
authenticated decryption verification, with server UTC bookends after writer
shutdown. The separately protected recovery identity matched. No plaintext dump
was saved or printed. The encrypted file remains in the approved local
`.check-results/p07-release` folder, with recovery material protected separately.

Reviewed migration 0005 succeeded, then only backend/frontend were recreated
from the exact tested images without rebuilding or pulling. The original private
database container `5d0ab1293dd015846de301c7d732933d595538118ae535e4cb7f13951bcfd427`
and its volumes were preserved. New backend
`74ddd36d825f25b6a08b32b6455ae57a2a96dab3799b45d09a4c8839886e764d`
reports ready on schema 5. Frontend
`b05ce5994c4196661707c6b3629098b3f52222543c108a254b45c01548abc990`
is healthy on the tested Opal image. UID, read-only socket, network-none database,
resource bounds and activated password/registration/recovery/mail settings all
passed verification. The web mail worker remains disabled and has no Resend key.

Cloudflare served the exact container assets:

| Asset | SHA-256 |
| --- | --- |
| `/assets/index-UcEH1IkK.js` | `f85153046ed6f17a9398bb1ed0ac178ba382df89277fcbd9b9d98036db6a8d70` |
| `/assets/index-CADnTdTB.css` | `b124b254db185d9377e96601b1c9c978b13994908d30a5d7c7c72001d8bf8670` |

Public root, sign-in and health returned 200. Anonymous identity, analysis status
and events returned 401; public readiness stayed 404. A clean Chrome profile
loaded those assets and confirmed enabled email/password fields and registration/
recovery links. Its screenshot was reviewed and browser/profile cleanup passed.
This public check used no account, dataset grant or model request; authenticated
progress/cancellation semantics were verified in the isolated feature suites.

The hash-identical original cron was restored after schema-5 readiness and the
compatible backend tag were verified. Its guard then released successfully.
The next scheduled worker reported `idle` at `2026-10-27T01:40:02.009753Z`, with
cron active and exactly one managed line. No mail attempts, quotas or leases were
reset. Credential-free release evidence is in
[`evidence/p07/production-release.json`](evidence/p07/production-release.json);
private environments, dumps, keys and bearer values are excluded.
