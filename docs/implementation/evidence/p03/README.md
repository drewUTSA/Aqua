# P03 evidence ledger

Final acceptance uses the candidate image identified in `package-verification.json`,
not only source mounted over a dependency image. `integration/report.json` requires
all 835 collected cases to pass in at least one dataset and both fixture exits to
succeed. Dataset skips are complementary; none remain unverified. `integration/`
contains exact JUnit/text, package inventory and resource/restore/cleanup reports.

| Red finding or attack | Defense/fix and passing evidence |
| --- | --- |
| Malformed/oversized Google credential reflected by default 422 validation | Fixed generic 422 handler; two route regressions pass in final matrix. Initial failures retained in development-red |
| Copied challenge sequential/parallel replay | Atomic consume commits before provider; one verifier call/one session, replay403 and fixed safe event |
| Concurrent first login, email collision and session fixation | Subject/advisory and user locks plus DB uniqueness; no email auto-link; fresh unpredictable tokens |
| Copied cookie after logout/epoch/status/revocation | Current durable checks deny; failed revoke transaction rolls back, returns503, retains cookie and permits retry |
| Grant resurrection or stale dataset/provider/cache context | Provenance and revoked tombstones; current grant version/epoch/approval; request-owned settings bind retrieval, execution and model cache |
| Cookie/peer churn and concurrent logins seeking more work | Committed peer/global/account counters, fixed key cap/no live-quota eviction, atomic session cap; denial causes no verifier/upstream work; cooldown succeeds |
| Session-cap scan through idle-expired history | Covering owner/epoch/idle index with stable time; 5,000-record execution plan/buffer regression |
| Storage saturation/outage, dirty lease and restored sessions | Bounded waiters/timeouts, reset/rollback, fixed503, successful later reads; synthetic restore preserves ACLs and applies epoch/challenge fence |
| Frontend P02 accepts old subject-only contract | 9 expected baseline failures in frontend-contract-red;54 Node/44 browser checks pass with canonical ID, failed logout lock and late-response isolation |
| Proxy bootstrap/query/Google flood, forged headers and aliases |48 bounded requests in network-none namespace, exact admitted work, independent budgets and recovery in integration/proxy.json |

The initial development run also exposed test-fixture queue contention, a migration
version-fixture collision and stale readiness expectations. Those fixtures were
corrected; production connection/queue limits were not loosened. A separate cold
pool/one-waiter saturation check still verifies denial and recovery. Final JUnit
contains no failures. Source/lock/secret-canary checks and advisory results are
stored alongside these reports. Fake private strings in red output are synthetic
canaries, never operator credentials.

Tests use synthetic accounts/databases and fake Google/model/email. No production
rate flood, real customer query, production-scale benchmark, real email or real
backup recovery was performed. P02 public smoke and live DB readiness are separate
in `../p02-release`; schema2 and durable auth are not yet deployed. P04/P07/P10/P12
remain required for their password, AI-admission, account-control and capacity gates.
