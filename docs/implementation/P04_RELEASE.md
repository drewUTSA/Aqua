# P04 release

**P04 is deployed with schema 3; password and account-mail features remain disabled.**
The merged package passed its isolated release checks, a fresh encrypted off-server schema 2 backup was collected, and cutover, private verification and the 12-request public smoke check passed on 2026-10-21. Password forms and mail activation remain later gates.

## Source and package

- Merged [PR #41](https://github.com/drewUTSA/Aqua/pull/41), main commit `067fb5a0aacc90ce646138fedbb770ecea6f0c92`.
- [CI run 39544907696](https://github.com/drewUTSA/Aqua/actions/runs/39544907696) completed successfully.
- The server checkout was fast-forwarded from `c25a3332e67f644e94c6ab3b6e80155dacf7c56b`. The pre-existing, unread `.env.bak` remains untracked.
- Deployed backend: `sha256:b253e68f307957d232819991057416910d86e407173dde876c3dee193602bedb`.
- Deployed frontend: `sha256:99d5ee833dc643155e1df01fdf38d992215cebde5a0fc31da8ac77c5f3364cd9`.
- All 67 expected backend runtime, migration and corpus assets match their source hashes. Nginx configuration SHA-256 is `09d379dad3dcc705f0346b654f5d9598a31b5c1b115412424002653d4e84fa03`. Dependency consistency and corpus validation passed.

The packaged password corpus contains 10,898 entries, is 708,370 bytes, and has SHA-256 `a5b8b74b66c0ed54d90098285cb0dbe02217ae41d7c91f0c57cf4a761e14521a`. The digest list, provenance and MIT license are packaged together; Git pins their line endings.

## Checked behavior

The disposable fixtures exercised synthetic data and fake provider transports. There were **1,056 distinct backend cases, each passing in at least one fixture**: bank passed 1,037 with 19 dataset-specific skips; Pagila passed 1,044 with 12 dataset-specific skips. Both completed without failures. The existing Starlette test-client deprecation warning remains recorded.

The proxy exercise passed **98 requests**, including **42 admitted fake upstream operations**, with independent password route budgets, bootstrap limits, shared concurrent admission, caller/header churn, `429` recovery, no-store error responses and private readiness enforcement. The disposable installer passed bootstrap, repeat migration, SCRAM authentication, runtime DDL denial and recovery, disabled networking and absence of a TCP database port. Test resource cleanup was confirmed.

Synthetic dump/restore preserved rows, grants and the recipient mail budget. The session, password-hash and pending-mail restore fences were applied. These checks used in-memory synthetic dumps; they do not establish a production restore.

The Argon2 microbenchmark used 32 samples with concurrency 2 and parameters 19,456 KiB, two iterations and parallelism 1. Hash p50/p95 was 14.288/22.757 ms; verification p50/p95 was 14.189/15.856 ms. Maximum RSS was 64,052 KiB. This two-CPU synthetic container measurement is not full login latency, production capacity or the later mixed-load acceptance gate.

P04 development red/blue evidence remains in [P04 evidence](evidence/p04/). The merged package retest and file digest manifest are in [P04 release evidence](evidence/p04-release/README.md). Existing failures were retained as development evidence; the release retest did not waive failures.

## Backup, cutover and live boundary

At source synchronization and candidate build, the P03 services remained healthy with schema 2. Cutover then explicitly applied schema 3; repeat migration passed and private storage readiness reported schema 3. Both activated containers are healthy and match the deployed image digests above.

The effective password authentication, registration, recovery, account mail and mail worker flags are all false. No mail provider key, outbox key, private mail secret mount or project mail worker is present in the web runtime. The reports' `flags_disabled: true` records those flags being disabled. No production account email, provider login callback, model request or hosted business-database query was performed for these release checks.

A fresh encrypted off-server backup tagged `pre-p04-067fb5a` was collected at `2026-10-21T22:34:08.9687106Z`, snapshot `78be69244e2127185de80acd0c9872453efe9d37b7be80b05dfcc6f3b3791d19`. The **operator-supplied helper receipt** records schema 2 before and after export, source commit `067fb5a0aacc90ce646138fedbb770ecea6f0c92`, and a passed encrypted repository data-integrity check. The earlier automatic attempt stopped at the Windows physical-path guard before secret access or SSH; the operator ran the reviewed helper in ordinary PowerShell. No plaintext dump was saved and no pruning occurred. **A production restore was not performed.**

Private verification confirmed migration checksums, runtime DDL and migration-ledger access denial, required recipient-ledger privileges, recovery, disabled container networking and no public TCP database port. The public check made 12 bounded requests across `aqua-ai.us` and `api.aqua-ai.us`: liveness passed, readiness stayed private, unauthenticated and legacy sessions were denied, oversized input was rejected, Google bootstrap configuration retained secure-cookie protections, and the disabled password bootstrap failed closed. It followed no redirects and made no provider or data-query requests. The sanitized backup, cutover, private verification and public receipts are preserved in the release evidence.

**Do not roll back to P03/schema 2 after schema 3 commits.** Preserve the database and durable security state; use maintenance and a forward fix. A recovered schema 2 backup must be migrated to schema 3 before running fences that reference the P04 tables, with all workers detached.

Password forms, working mailbox links and deliberate mail-worker activation remain separate P05/activation gates. Disabled deployment does not authorize sending mail or opening registration. See [P04 password cutover](../ops/P04_PASSWORD_CUTOVER.md) and [P04 account mail operations](../ops/P04_ACCOUNT_MAIL.md) for key handling, worker budgets, delivery verification and restore rules.
