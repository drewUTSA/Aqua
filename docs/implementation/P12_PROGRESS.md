# P12 capacity and AI reliability — implementation in progress

## Ordinary record counts and follow-up history

Employees can ask how many reviewed records exist or specify a numeric amount threshold. For example, “How many transactions have an amount greater than 957.25 CZK?” uses the bank transaction amount. Aqua checks the selected tables and field types, validates the SQL and executes with the read-only analytical role. Counts with prior context, unsupported units, additional filters or grouping continue through the existing question pipeline.

In a signed-in synthetic check, both versions saved all four expected numbers. The earlier version asked the fixture provider for SQL four times. The revised version made zero generation calls and saved the four results in 0.677–0.894 seconds. Two unsupported controls still reached the provider and preserved the normal service error. These timings used a local counting provider and synthetic PostgreSQL data.

Private follow-up admission keeps the same eight-turn window and prior-SQL limit. With eight 900-row saved results, it read 547 bytes of PostgreSQL result fields, down from 1,032,883. Across 24 alternating pairs, median context selection and decoding took 1.70 ms, previously 3.82 ms. With eight single-row results the medians were 0.54 and 0.50 ms respectively. Every pair produced the same context and digest.

## Recover a timed-out ranking

On a saved ranking timeout, **Try again** repeats the original question. **Rank groups in a new chat** opens the guided ranking form in an empty chat for the same project. Enter a source and grouping field, choose a measure and tie rule, and select **Use this draft**. Review the generated question in the ordinary composer and press **Send**. The first chat remains available in private history.

The shortcut is available to employees with permission to query and read their results. Aqua checks the selected conversation, saved request and current access when the employee opens the form. Opening it sends no analysis request. The employee can leave the form without submitting a question.

In the private browser rehearsal, a synthetic gateway timeout interrupted the original typed question. Both websites opened the blank form with the keyboard. After manual submission, Classic displayed both tied accounts and their counts in 1.417 seconds and Opal in 1.366 seconds. Each account had 500 transactions. Both results used zero additional provider calls. Each employee could reopen their own two chats, and a separate employee was denied access.

## Employee-selected group rankings

**Rank groups** handles one authorized fact source, one grouping field, and either a row count or the sum of one eligible numeric field. The employee can choose an exact number of groups, every group tied at the cutoff, or every group in the requested number of distinct score levels. Aqua uses the existing query validator, read-only database role and row cap. The displayed result identifies its source as **Aqua grouped ranking**. An unsupported command receives a specific correction message without invoking the model. [Walkthrough](SALES_DEMO_20261118.md#rank-groups-in-a-new-chat)

An independent trial of automatic recognition compared the selected chat planner with a prospective revision on 12 fresh questions. Correct answers within 45 seconds increased from 6 to 7 and timely tied rankings from 3/7 to 4/7. Both versions answered seven correctly overall, made 12 provider calls and timed out twice. None of the questions used the automatic database route. That revision was held. [Automatic experiment](https://github.com/drewUTSA/Aqua/pull/106)

A separate experiment supplied six deliberately incorrect first SQL drafts and asked the installed 8B model to repair each one against restricted PostgreSQL. Turning off reasoning for the repair saved a median 5.161 seconds per pair and reduced accuracy from 5/6 to 4/6. The current repair setting remains selected. The timer started at the supplied draft.

## Employee timeout and retry

Aqua tells an employee when the model failed to answer in time. When the final provider attempt reaches a read timeout or returns HTTP 504, Aqua produces the retryable `model_timeout` response. An ordinary provider outage retains the existing retryable `model_unavailable` response. The configured deadline and fallback policy still apply.

In an isolated signed-in rehearsal, a real HTTP connection to a synthetic provider accepted an employee request and withheld the reply. The signed-in employee API returned the timeout in private history after 46.63 seconds. Calling the endpoint used by **Try again** on the original input saved the correct count of 267 in 1.03 seconds once the fixture could answer. Replaying the completed retry made no extra model call. Separate gateway 504 and service 503 responses produced the intended distinct messages. [Verification](evidence/p12/employee-timeout-20261119.json)

On a separate 141-record fictional ledger, the selected ranking source and an experimental grouped-query change each made 12 real Qwen3 8B calls. Each version returned six correct answers, five within 45 seconds. Among six grouped ties, each returned one correct answer on time, one correct answer late, one incorrect answer and three provider timeouts. All nine paired saved answers had identical SQL and result hashes. Across both viewers, all 366 baseline reads and all 369 experimental reads passed. The proposed change stayed out of the application. Four brief CPU-only tasks may have overlapped the first seven baseline questions. An optional SQL inspection failed after scoring. These runs establish the employee-visible outcomes and do not establish a speed gain. A separate controlled SQL fixture on the held branch verified all three qualifying teams in the actual worker and matched the stored answer to both signed-in responses. It used zero real model calls. [Controlled readback](evidence/p12/presenter-and-browser-20261119.json)

An eight-question diagnostic used the selected feedback runtime, a 165-row fictional ledger and the real Qwen3 8B model. The private relay observed timing on the upstream stream, discarded reasoning text and returned a complete response to the application. All eight answers were privately saved, and seven were correct within 45 seconds, including all four rankings. Both viewers completed all 183 reads. Model loading took under 0.10 seconds on every call. Processing the first prompt took 17.73 seconds and each later prompt took at most 0.05 seconds. Two calls spent 23.50 and 29.57 seconds generating tokens. All eight finished, so the phase of the older timeouts remains unknown. [Phase timings and measured scope](evidence/p12/provider-phase-timing-20261119.json)

## Presenter preparation on the first question

Three fresh questions each ran in three separate, identically configured model sessions. The first condition only preloaded the model. The other two added one preparatory request capped at one generated token, either unrelated text or the presenter's authorized fictional schema. All nine employee answers were correct and privately saved within 45 seconds, and all 204 viewer reads passed.

After the schema primer, each employee request reused 1,208 prompt tokens. Compared with preload alone, it shortened the employee’s wait by a median of 13.61 seconds across the three paired questions. The unrelated primer reused three tokens and was faster than the schema primer in all three comparisons. The schema primer took 17.23–18.09 seconds to run. Including setup and preparation, it reached the saved answer a median 1.03 seconds later than preload alone. The existing presenter rehearsal remains the recommended preparation for this synthetic demonstration. [Experiment and scope](evidence/p12/presenter-and-browser-20261119.json)

## Fresh ranking and timing comparison on November 19

One presenter asked the same 16 questions against the same 131-row fictional ledger on main `6ee361f` and candidate `0472139`. Two other signed-in employees read their own history. A correct answer had to match the expected table and appear in its owner's saved history within 45 seconds. Python, SQLite and the restricted PostgreSQL reader agreed on the expected answers. [Candidate change](https://github.com/drewUTSA/Aqua/pull/101) · [Aggregate results](evidence/p12/ranking-and-calendar-20261119.json)

| Questions | Baseline | Candidate |
| --- | ---: | ---: |
| Explicit ties | 3/4 | 3/4 |
| Distinct ranked values | 0/2 | 2/2 |
| Exact number of ranked records | 1/2 | 2/2 |
| Calendar counts | 6/6 | 6/6 |
| Other controls | 2/2 | 2/2 |
| **Correct saved answers within 45 seconds** | **12/16** | **15/16** |

The candidate gained one explicit-tie answer and lost another to a provider timeout. All 32 assignments called Ollama. The candidate used the existing model weights. Among saved answers, the median went from 13.66 to 16.68 seconds and the 95th percentile from 37.87 to 42.39 seconds. The timed-out assignment counted as incorrect. Viewer reads passed 396/396 on baseline and 411/411 on the candidate. The study used consecutive runs on one PC.

On a separate 165-row fictional ledger, the candidate met the sales-demo target with **18/20** new questions correct within 45 seconds. Nineteen answers were saved on time. One calculation returned a wrong table and one ranking timed out. All 465 viewer reads succeeded. Median saved-answer latency was 9.13 seconds and the 95th percentile was 33.34 seconds. All 20 assignments used Ollama. The judge recognized database-only answers before this second test started. The same questions, gold tables, ownership requirements and deadline were retained.

The submitted PR 101 source `b5e94ff` differs from the measured `0472139` by one blank line removed by the project's formatter. The parsed Python matched, and the rebuilt image's 243 application files matched the submitted commit. A separate signed-in test simulated an unavailable provider. Three supported calendar questions saved correct answers without a provider call. A question with an additional filter returned the existing retryable error.

A subsequent experimental direct ranking tool was held after a new paired test. On another fictional ledger, both versions scored 9/12 within 45 seconds, including 3/4 tied extrema and 0/2 requests to include peers at the cutoff. All 24 assignments called Ollama. Both arms had zero provider timeouts. Viewer reads passed 294/294 and 291/291. The experiment's additional 20-question general confirmation remained sealed because the paired criterion failed. [Research PR](https://github.com/drewUTSA/Aqua/pull/102) · [Paired evidence](evidence/p12/ranking-and-calendar-20261119.json)

## Three-person demo acceptance

**The November 18 local sales demo reached its target of 18/20 correct answers within 45 seconds.** Each of the three studies below used one presenter submitting questions and two other signed-in employees reading their own profile, history and saved results. The timer ran from submission until the employee could read the saved answer through the job and its private history. All assigned questions counted, including application errors. [Current handoff](../../AQUA_CODEX_HANDOFF.md) · [Aggregate evidence and receipt hashes](evidence/p12/three-person-demo.json)

| Study on fictional financial data | Saved within 45 seconds | Correct and saved within 45 seconds | Successful viewer reads |
| --- | ---: | ---: | ---: |
| Original 20-question acceptance | 18/20 | 17/20 | 513/513 |
| Paired research, 20 new questions with the release prompt | 19/20 | 12/20 | 981/981 across both arms |
| Same 20 questions with an additional planning instruction | 19/20 | 14/20 | Included in the paired total |
| Final acceptance, 20 new questions on the PR 93 source | **19/20** | **18/20** | **489/489** |

On the final run, calculations, filtering and joins scored 4/4 each. Rankings and calendar questions scored 3/4 each. One ranking returned one of two tied winners. One calendar request reached the provider socket deadline at 45.024 seconds. Across all 20 assignments, the median, P90 and P95 time to any saved answer were 12.14, 33.32 and 37.87 seconds. For a **correct** saved answer, P90 was 37.87 seconds and P95 had no finite value because two questions lacked a correct delivery. Both viewers made verified reads during every presenter job. Viewer P95 was 9.44 ms.

The test used pinned Ollama Qwen3 8B, the release prompt, a real application worker and restricted PostgreSQL. Independent Python calculations, SQLite and PostgreSQL agreed on all 20 expected outputs for the 178 invented records in eight tables. The tested source `3058f951` and merged main `1cfbe2c` have identical trees. PR 93 corrected code and label rendering. Each study used a different question set. Attributing the difference between 17/20 and 18/20 to the formatter would require testing both versions on matched questions. All three studies used the existing model weights. [Formatter change](https://github.com/drewUTSA/Aqua/pull/93) · [Main CI](https://github.com/drewUTSA/Aqua/actions/runs/44408656430)

The 14-minute walkthrough uses its own checked-in 1,000-transaction fixture. The 178-row qualification fixture, frozen questions, per-job receipts and local model cache are kept separately from this checkout. The aggregate evidence allows another operator to check the reported arithmetic and identify the original receipts by digest. Running the walkthrough on three devices still requires a prepared private HTTPS origin and synthetic accounts. Operational capacity, service objectives and employee sign-off remain open. [Presenter setup](SALES_DEMO_20261118.md)

## November 16 mixed HTTP local qualification

The explicit [mixed HTTP capacity mode](MIXED_HTTP_CAPACITY.md) adds a fresh,
bounded real Uvicorn/auth/history/job/metadata-stream workload over the existing
disposable storage fixture. It preserves the original component measurements,
all production budgets and source-only archive. Ninety-six fixed reads, six
closed fake analyses, cancellation/queued recovery and two actual HTTP stream
disconnects pass on the final combined local source, with exact-resource cleanup;
current PR and main CI remain required. No production SLO,
external provider, GPU/OS-child or public-network backpressure result is implied.

## November 16 learning qualification

The subsequent [learning and companion foundation](LEARNING_PROGRESS.md) adds a
bounded existing-model evaluation path, offline context/capability contracts,
monthly numerical trend learning and reviewed supervised-data export guards.
The real qwen3:4b baseline completed 22/24 synthetic held-out SQL cases after
four separate pilots. No Ollama weights or production routing changed. These
component results and offline foundations do not close broader P12 capacity,
trained-adapter qualification or the P11/P13 release gates.

## Scope

Ben authorized continuing the remaining phases and improving how Aqua's AI
works, retaining the existing tests. Production backup/recovery and activation
are handed to his personal computer as recorded in the release handoff. This
branch prepares independent P12 code; it does not complete the P11 release gate.

Ben's subsequent GH Logistics local-AI request adds a separate
[reviewed knowledge/hybrid retrieval slice](AI_KNOWLEDGE_PROGRESS.md), with an
offline paired holdout gate. Hybrid retrieval remains off pending real held-out
evaluation. These additions do not close the mixed-workload or release gates.

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

The November 18 three-person run provides a measured end-to-end workload for the
local demo. Operational P12 acceptance requires a deployment-specific load mix,
service objectives, documented capacity limits and intended employee review.
The earlier component checks retain their original scope. [Current handoff](../../AQUA_CODEX_HANDOFF.md)
