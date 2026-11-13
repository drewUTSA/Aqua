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

This is a component microbenchmark on the office PC, not a total-application
speedup, p95 capacity guarantee, hardware-independent result or measured model
accuracy gain. Linux qualification and broader P12 measurements remain required.

## Verification and remaining gates

Ten pure graph cases and six pure follow-up input cases pass locally without
providers or a database. Added backend integration tests exercise actual schema
assembly and the real retriever with a fake embedding and connection. Those tests
still require the canonical Linux backend matrix. Source/lock/format checks,
both full synthetic dataset matrices, all retained browser jobs, image/source
qualification and release checks must pass on the final integrated candidate.

Complete P12 also requires private-list/query-plan measurements, cold/warm schema,
provider stage/cancellation/slow-stream behavior, pool saturation/recovery,
chart/bundle/resource measurements and documented capacity limits. Current model
accuracy must be measured separately using an explicitly bounded synthetic
evaluation; the fake-provider tests establish protocol behavior, not model quality.
