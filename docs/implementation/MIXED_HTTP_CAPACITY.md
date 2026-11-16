# Bounded mixed HTTP capacity qualification

November 16, 2026. This adds an explicitly selected measurement mode to the
existing `run_capacity.py`. Its original deep-history, metadata and pool
measurement command and fixture remain unchanged. The final combined-source
local workload and retained components pass with complete cleanup. Exact-head
PR and subsequent main CI remain required before integration. No production runtime file, migration,
dependency, limit, feature flag or model route changes.

## Fixed workload

The existing original-size disposable PostgreSQL/test-container pair is created
fresh. Containers retain network isolation, no published ports, two CPUs/1GiB
per-container limits and the existing bounded tmpfs/PID contracts. Only the
existing code/SQL/fixture stdin archive is copied; no dotenv, host mount,
credential store, frontend archive or production configuration is admitted.
The selected runtime must already exist at an immutable image ID. Windows
requires `desktop-linux` at exactly `npipe:////./pipe/dockerDesktopLinuxEngine`;
Linux CI requires `default` at exactly `unix:///var/run/docker.sock`. Active
context and endpoint metadata are checked before creation. Docker host/TLS/cert,
config and API environment overrides or remote context selection are refused.
Every provision, probe, ownership inspection and removal command then uses that
same fixed local host with a minimized environment; later context-file changes
cannot redirect cleanup.

Real Uvicorn serves the actual Aqua ASGI routes on an ephemeral loopback port
inside that network-none namespace. Four accounts and durable sessions are
seeded through the existing `IdentityStore` fixture seam; exactly two receive
the synthetic dataset grant. Each owner has twenty synthetic history entries.
The workload first verifies that the two account-only owners cannot submit
analysis, then admits two held and two queued fixed fake jobs. It runs exactly
96 session/profile/history GETs across four concurrent clients: 32 observations
per route, spread across all four owners. Responses must retain current owner
isolation, bounded pages, no-store headers and unchanged session idle expiry.

Two real metadata SSE HTTP connections remain open during the mix. One reads a
small fixed prefix slowly; both read a closed metadata event and disconnect.
Their durable stream slots must be released. The workload then cancels the two
held analyses, observes real dispatcher/settlement of cancellation and queued
recovery, and admits one further completion per granted account. Six jobs total
must finish as exactly two cancelled and four complete, with no physical fake
work or retained capacity left active. Account/history reads must still recover.

The fake engine replaces only generation/execution work and accepts the six
fixed synthetic questions, fixed dataset and two seeded principals. Production
authorization, durable admission, four-call reservation, two global/one owner
execution policy, 120-second job deadline, cooperative control, snapshots,
cancellation, streams, persistence and settlement remain actual application
code. Network/libpq guards admit only that loopback HTTP port and the existing
two fixture application DSNs; asynchronous DB/provider transport is denied.
Any actual provider construction attempt fails the measurement.

## Ceilings and measurements

- 180 seconds for the whole host fixture, including provisioning and the probe;
  60 seconds separate exact-resource cleanup. Every provisioning Docker call
  receives the remaining whole-fixture deadline.
- The probe permits 150 seconds of work and at most 15 seconds to stop the
  Uvicorn/dispatcher threads. The runner never retries or falls back to a live
  service. A timeout stops work and leaves qualification failed.
- At most 200 HTTP requests, four concurrent mixed-read clients, six total
  concurrent HTTP requests including streams, six fake jobs and two stream
  connections. Read bodies are at most 64KiB; request bodies at most 4KiB.
  SSE observations are at most 24 events/8KiB and verify metadata-only fields.
- Report throughput and nearest-rank p50/p95 with sample counts. p95 is omitted
  below twenty observations; p99 is never reported by this small fixture.
  The exact 96-read mix has its own timings; the all-HTTP distribution also
  includes setup, job and final recovery traffic and is labeled separately.
- Record process peak RSS and CPU seconds for the combined app/client process;
  those values exclude PostgreSQL and the Docker daemon. They are observations,
  not a new memory allowance or a production capacity maximum.

Receipts are create-only, including a failed run. They retain counts, bounded
latencies, status categories, source/image identities, partial observations and
cleanup metadata, never cookies, CSRF values, account records, question/SQL/result
bodies or raw driver/provider errors. Every run registers fresh container names
before create, verifies exact name/ID/image/purpose before removal and confirms
absence. Unknown cleanup stays failed; no broad container/volume prune occurs.

## Execution

From a trusted checkout with the existing pinned test images prepared, run the
offline guard first:

```text
python tools/checks/test_mixed_capacity.py
```

Then select the new mode with the actual existing immutable image ID and a fresh
local receipt path, on the platform's verified local Docker context:

```text
python tools/checks/run_capacity.py --mixed-http --image sha256:REVIEWED_EXISTING_IMAGE_ID --output .check-results/capacity/mixed-http.json
```

The CI step resolves its already built runtime to its actual image ID. The
original capacity command is still executed separately and both JSON receipts
are retained. Running the mode against a remote Docker context is refused.

## Initial actual local measurement

The frozen source executes successfully against the existing pinned dependency
image `sha256:61034825653941c528a17bd66d3d0072c18b1a57d82377053d349d6204c7ef66`
in local network-none disposable storage. This is a check image, with the
candidate source copied through the retained stdin archive. It is not a claim
that the installed runtime image itself contains these test helpers.

[The complete initial receipt](evidence/mixed-capacity/mixed-http.json) records
130 HTTP requests with maximum six inflight,96 mixed reads (32 per route),
two metadata streams/disconnects, six fake jobs (two cancelled/four complete),
zero real provider calls and complete app/dispatcher/container cleanup. The
whole fixture took13.843seconds; the96-read mix took1.1961seconds (80.2628
completed reads/second for this workload). Its p95 observations were session
36.1723ms, profile87.674ms and history65.8019ms. Process peak RSS was112316416
bytes, excluding PostgreSQL and the Docker daemon. These are local synthetic
measurements with small sample counts, not production service objectives.

[The original component workload](evidence/mixed-capacity/retained-components.json)
also passes separately, with10000-chat traversal, Bank/Pagila metadata and
bounded pool saturation/recovery unchanged. Both initial receipts bind source
archive `e39539331136547dbc79cea96c75d6a090510291f14b76cc9619ea4ce8332e3b`.
Combined-source integration and exact-head/main CI remain required. Earlier
source-preparation wording above describes the implementation checkpoint.

## Final combined-source local qualification

After integrating the reviewed UI and companion source, including its exact
runtime-inventory fixture guard, [the final mixed HTTP receipt](evidence/mixed-capacity/mixed-http-final.json)
and [retained component receipt](evidence/mixed-capacity/retained-components-final.json)
both pass. They bind source archive `237c2346775bc9bd9c7b2339f7f6fc118a15a7bec28516729235e223a77d159a`.
The final mix records 131 HTTP requests,96 mixed reads,
six fake analyses (two cancelled/four complete), two actual metadata-stream
disconnects, zero real provider calls and confirmed exact-resource cleanup.
The local whole fixture took8.297seconds. These observations
retain all limitations above; they establish no bank connector, model quality,
production peak load or banking-service commitment.

The published JSON uses LF. [Publication provenance](evidence/mixed-capacity/publication-provenance.json)
binds each untouched private raw receipt to its published bytes; only CRLF-to-LF
normalization is admitted. Initial receipts remain as historical observations.

## Remaining acceptance

This is a small synthetic HTTP/application test. It does not measure a TLS
edge/tunnel/nginx rate-limit chain, a browser cookie jar, real login/password/mail
or Google delivery. Seeded sessions still go through actual HTTP authentication,
but identity bootstrap is not being benchmarked. No analytical SQL, external
model, fallback chain, GPU or restricted child-process execution is used; retained
provider/process/cancellation tests remain independent and required.

Slow bounded reads and actual disconnects do not fill the kernel send buffer or
prove public-network backpressure saturation; the retained stalled-ASGI send
deadline test remains necessary. This workload also does not qualify Plotly
rendering cost, hybrid/model accuracy, a representative peak-user load, RPO/RTO
or a production SLO. Broader representative workload/provider/staging and device
acceptance remain open P12/P13 gates.
