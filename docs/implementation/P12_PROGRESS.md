# P12 capacity and AI reliability — implementation in progress

## Scope

Ben authorized continuing the remaining phases and improving how Aqua's AI
works, retaining the existing tests. Production backup/recovery and activation
are handed to his personal computer as recorded in the release handoff. This
branch prepares independent P12 code; it does not complete the P11 release gate.

## Bounded retrieval graph

The previous table selector called `Schema.related` for every catalog relation,
repeatedly scanning all tables and columns. It could supply a single bridge
between selected relations but omit longer joins such as payment → rental →
inventory → film, leaving the model without intermediate schema definitions.

The candidate builds request-local bidirectional adjacency once from the same
approved references and `_id` column heuristic. It preserves the existing
one-step bridges, then fills deterministic shortest paths with at most twelve
anchors, five hops and eight additional relations. Unknown relations are excluded;
disconnected tables stay disconnected. No new data access, persistent cache,
provider call, schema migration or dependency is introduced. SQL validation and
read-only execution remain independent and unchanged.

Graph construction is O(tables + columns + references). At most twelve bounded
searches follow; each visits a graph node at most once. Tests count actual column
sequence visits and cover cycles, disconnected graphs, ties, request isolation,
unknown references, additional-table/anchor limits and real context assembly.

## Follow-up embedding context

The vector lookup previously embedded only the newest question even when the
generator had approved prior turns. A follow-up such as “And last month?” could
therefore retrieve unrelated schema before generation saw its conversation.

The existing single embedding call can now include the two most recent distinct
questions from that job's already frozen, owner/dataset/grant-fenced context.
Only question fields are serialized as data; SQL, rows, identifiers, receipts,
settings and other fields are excluded. The input is capped at 12,000 UTF-8 bytes;
older questions are omitted whole to preserve the current question. Standalone
questions retain their original input. The four-call/120-second job budget,
provider policy, expiry, cancellation and current-grant checks are unchanged.

## Initial measurements

`tools/checks/benchmark_retrieval_graph.py` compares the preserved earlier
selection algorithm and the candidate over synthetic chain catalogs, with five
samples each and eight columns per table. The local Windows/Python3.12.10 run
measured the following medians. Both implementations keep every previously
selected relation; the candidate additionally supplies the missing join paths.

| Tables | Earlier column-sequence visits | Candidate visits | Earlier median ms | Candidate median ms |
| --- | --- | --- | --- | --- |
| 24 | 480 | 24 | 1.1380 | 0.1102 |
| 128 | 15,872 | 128 | 122.1768 | 0.4255 |
| 512 | 260,096 | 512 | 1,337.8202 | 1.7713 |

The same experiment passed in the pinned Linux/Python3.12.14 image. At 512
tables, the medians were 603.3419ms before and 1.5289ms after; column visits
were 260,096 versus 512. See [the Linux receipt](evidence/p12/retrieval-graph-linux.json).
This is a component microbenchmark, not a total-application speedup, capacity
guarantee, hardware-independent result or measured model accuracy gain.

## Isolated Linux capacity measurements

The new `run_capacity.py` reuses the existing networkless, portless disposable
PostgreSQL fixture, two-CPU/1GiB container limits and source-only stdin copy.
It never mounts deployment files, loads production environment or calls providers.
The actual `workspace.history.list_chats` implementation traversed 10,000 distinct
chats owned by one synthetic account alongside 100 accounts with 20 chats each.
All 100 pages had distinct IDs. With thirty samples, first-page p50/p95 were
0.4831/0.6104ms; page100 was 0.4747/0.4808ms. The representative deep-read
`EXPLAIN (ANALYZE,BUFFERS)` used `chats_owner_activity`, with eight shared-buffer
hits and no disk reads in the measured plan. No index or production limit changed.

First catalog loads took 6.4921ms for Bank and 3.8780ms for Pagila; thirty
same-connection repeats had p95 1.4398ms and 1.5597ms. These are fresh-fixture
first loads and warm repeats, not a system cold-cache claim. At a deliberately
smaller one-connection/one-waiter pool, overflow was rejected in 0.1416ms; the
queued operation completed after release and thirty recovery reads had p95
0.5844ms. Readiness returned ready. Exact resources were removed and absence
confirmed. See [the capacity receipt](evidence/p12/capacity-linux.json).

An initial runner invocation reversed two fixture arguments and failed before
container creation. The corrected invocation uses explicit keyword arguments;
the failed run is retained in the task's local verification logs. Thirty
samples support a limited p95 description, not a p99 estimate or a mixed-user
HTTP SLO. This server was also running the existing application, so these
bounded measurements are useful comparisons rather than isolated-host maxima.

## Verification and remaining gates

Ten pure graph cases and six pure follow-up input cases pass on Windows and
Linux without providers or a database. The canonical Linux matrix passed all
1,854 distinct backend cases, including three added integration tests for actual
schema assembly and the real retriever with a fake embedding and connection;
both datasets, eight core restore batches and two original export-capacity cases
passed with confirmed cleanup. See [the backend receipt](evidence/p12/backend-linux.json).
The 197-input runtime inventory matches source byte-for-byte, including the
security-patched lock and two new modules. Current native qualification profiles
were refreshed, preserving exact source, lock and image assertions. Source/lock,
Black and Ruff checks pass. Final PR/main CI and all retained browser jobs remain
required for the final integrated candidate.

The first P12 CI candidate `7ee8265` correctly stopped at the old compiled-file
count (191) in the closed36 fixture suite. Its inventory guard now requires
exactly the two named new retrieval modules, the original191 remaining entries
and 193 compiled inputs total. No case identity, skip allowance, resource limit
or runtime hash comparison changed. This structural inventory update requires
a fresh complete run; the earlier failed run remains recorded.

Complete P12 still requires broader mixed HTTP load and agreed production SLOs,
provider stage/cancellation/slow-stream measurements, chart/bundle/resource
measurements and documented capacity limits. Existing backend tests retain the
provider budget, real-process cancellation and bounded-pool recovery regressions;
they are not substitutes for a measured end-to-end workload. Current model
accuracy must be measured separately using an explicitly bounded synthetic
evaluation; the fake-provider tests establish protocol behavior, not model quality.
