# P04 evidence and retained findings

Final acceptance is `integration/report.json`: 1056 unique backend cases pass in at least one of the two isolated fixtures, zero failed or unverified cases. Dataset-specific skips are paired with the other fixture's passes. `integration/proxy.json` records 98 bounded requests against the actual candidate frontend image, admission/rejection counters, cooldown/recovery and temporary-resource cleanup. Proxy upstreams are synthetic counters; backend authentication behavior is covered by the matrix, not claimed from those proxy responses alone.

`package-verification.json` binds 67 runtime/corpus source hashes and nginx to the tested production images. It also records a 32-sample Argon2 microbenchmark, not service capacity. `deployment-check.json` records synthetic schema-3 bootstrap, SCRAM, repeated migration, runtime DDL denial/recovery and memory-only export. The final matrix records memory-only synthetic restore, ACL preservation and session/challenge/hash/mail fencing. Frontend JUnit has 71 cases, including 17 content/export safety regressions; no P05 password UI journey is claimed. Mail-unit JUnit has 19 offline cases, also represented in the full matrix. Advisory audits report no known vulnerabilities at the recorded check; this is not proof of vulnerability absence.

## Red findings, fixes and paired retests

| Finding | Correction | Final evidence |
| --- | --- | --- |
| Initial development matrix has 48 failures across both fixture runs: corpus assets missing from the test archive, immutable verifier spy, unstable parameter IDs and older route/challenge fixtures | Explicit corpus asset packaging, real-verifier proxy spy, stable IDs and reviewed route/purpose inventories; no required test waived | `development-red/` is retained verbatim; final actual-image matrix passes all 1056 unique cases |
| Correct-cost but malformed stored Argon2 encoding denied without normal dummy work | Strict canonical PHC format, base64 decoding/roundtrip and reviewed cost policy before choosing real/dummy verifier | `security-review-red.json`, paired manual `security-review-purple.json`, and final `test_password_hash_encoding` cases in both JUnit files; the manual retest's pending-matrix note predates final acceptance |
| Registration mail could consume FIFO/global capacity ahead of short-lived reset links | Purpose-reserved queue/hour/day allocations and security/reset priority; quotas survive retries/restarts | Final mail fairness/flood/recovery regressions in both fixture files |
| Generic known/unknown mailbox acknowledgements could expose short-circuit timing | Uniform configuration/capacity preflight and minimum 50 ms accepted email-work duration; any padding occurs after releasing the DB lease | Final password/mail admission tests; this is mitigation, not constant-time or production timing proof |
| Generic nginx 413 lacked no-store in the deployed P03 smoke | Server-level no-store for generic errors, retaining explicit static cache policy | Final candidate proxy oversize/no-store case |

Shared anonymous Google/password bootstrap quotas can still throttle legitimate login/recovery bootstraps until cooldown. Independent POST/mail budgets and bounded work are tested; end-to-end availability under flood is not guaranteed. Trusted visitor attribution and representative capacity testing remain separate work. Hash-slot crashes fail closed and need the reviewed stop-all-workers recovery procedure; slots never expire while a paused worker could still consume memory.

## Live release versus candidate

P03 release evidence is in `../p03-release`: merged source c25a333, tested release images, explicit schema 1-to-2 migration, private socket-only readiness, runtime privilege denials and bounded public health/auth-boundary smoke. The off-server encrypted backup report is operator-confirmed, integrity checked and contains no dump/password; production restore was not tested. One early release verification stopped on a concurrent disposable test directory and was rerun after exact cleanup; that guard failure is retained.

P04 remains uncommitted source for human review. No schema-3 production migration, password/signup flag, real email, provider callback, model/customer data query or worker schedule is activated. Tests use disposable synthetic databases and fake providers. No full live penetration test, production capacity or public launch readiness is claimed. Protected hosted-data modules, original handoff and applied migrations remain unchanged; see `source-quality.json`.


## Email and executable-content follow-up

The user's anti-spam/execution review found additional concrete gaps before P04 deployment. `security-followup/` retains the earlier candidate's results as historical evidence and paired red/blue probes. `../../P04_SECURITY_REVIEW.md` describes the strengthened current behavior and limits. The current `integration/` and package verification are the final acceptance for the updated code.

- Previous repeated requests created three distinct queued messages for one synthetic mailbox; the new rule coalesces them into one. Both disposable fixture red runs reproduce the old 3-versus-1 assertion and confirm cleanup. New tests exercise the five-minute cooldown, three-new-jobs rolling-24-hour recipient/purpose history, deletion/restart persistence, concurrency and recovery.
- Nine offline origin/template/recipient contract cases failed before correction and pass after. The new worker validates the exact purpose-specific template; enqueue/delivery check mailbox/proof/expiry/current reset epoch. No real mail is sent.
- SQL custom-operator/type-cast bypasses and object-identifier metadata resolution have paired before/after parser evidence. All 46 new validator cases plus prior regressions pass in the final isolated matrix; these probes do not claim that the hosted DB contains attacker-defined objects.
- Real ReactMarkdown SSR regressions prove the production renderer emits only approved formatting, with no generated images, active links, raw HTML or caller-selected plugins. Spreadsheet clipboard/export text is neutralized with delimiter-boundary regressions. Separate browser evidence is included when executed, with its own network interception and scope.

Global mail delivery caps remain 20 attempts/hour and 60/day, with reserved purpose allocations. Recipient limits count new logical jobs, not bounded idempotent retries. Alias addresses are not collapsed into identities; global caps remain necessary. No zero-abuse guarantee, unrestricted code-safety claim, full live pentest or production-capacity certification is made. P03 remains live; P04 flags/worker/schema-3 remain inactive.
