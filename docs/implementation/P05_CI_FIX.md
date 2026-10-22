# P05 browser-fixture startup correction

PR #42 is open on `codex/p05-opal-shell` at
`0ffb3bde154bc2e55b8fe253a25d6c3ef44d0853`. GitHub Actions run
[39694996814](https://github.com/drewUTSA/Aqua/actions/runs/39694996814)
passed the backend, database installer, proxy abuse/recovery, frontend unit,
dependency audit/build and 77 Opal synthetic browser checks. The next step failed
before any real-backend browser assertion with `bridge_unmatched_response`.
Classic CI steps did not run. This test-infrastructure follow-up is uncommitted
for human review. P05 is not deployed; the next GitHub run must pass after push.

## Defects and corrections

The old `pg_isready` check could accept PostgreSQL's temporary Unix-socket
initialization server. The entrypoint stops that server before executing the final
postmaster, so role/bootstrap or migration work could race a shutdown. The new
gate requires PID 1 to be exactly `postgres`, then checks `/run/aqua-app-db`.
Every operation and retry shares the existing 45-second deadline. TCP remains
disabled and Docker networking remains `none`.

The direct CI bridge mislabeled a terminal fixture startup failure as an unmatched
request ID and discarded startup/cleanup evidence. `FixtureBridge` now rejects
startup explicitly while retaining only allowlisted lifecycle metadata. Raw
frames, exception text, stderr, cookies and proof values are never logged.
Unknown IDs, duplicate readiness, malformed frames and size limits still fail.
Process close is observed after stdout drains, preserving the final cleanup
frame. CI summaries now include sanitized diagnostic and cleanup fields.

The exact pinned PostgreSQL image reproduced the readiness defect: a synthetic
initialization script held the temporary server open, and the old gate accepted
it while PID 1 was Bash. The corrected gate waited for the final postmaster and
its private-socket query passed. A bounded release barrier makes the CI regression
independent of scheduler speed. The original GitHub run did not retain its
underlying startup stage; this proves the readiness defect but cannot establish
retrospectively that it was the only cause of that run.

## Validation

- 133 frontend unit tests passed, including 13 new real-subprocess bridge cases.
- Seven startup regressions passed: temporary-server rejection, recovery,
  deadlines and blocking role/bootstrap work until final readiness.
- All 12 existing cleanup regressions passed.
- The pinned-image startup regression passed with network isolation, no TCP
  listener and removal confirmed. CI runs it before the real browser gate.
- Opal and classic each passed all 20 actual FastAPI/schema-3 PostgreSQL browser
  checks through the direct Python CLI used by CI. They cover malicious/replay
  rejection, valid login, session revocation, CSRF, dataset denial, actual 429
  and natural Retry-After recovery without automatic password retry.
- Source/lock guards, Black and Ruff passed. All 244 checked application/backend,
  hosted-data and configuration files match the preceding review. Both browser
  suites reused the exact unchanged production assets; report hashes identify them.
- All temporary browser profiles, listeners, containers and socket volumes were
  removed; absence was confirmed. No required failure was waived.

Reports and hashes: [`evidence/p05/ci-fix/`](evidence/p05/ci-fix/).
Earlier 120/77/20 results in `P05_ROLLBACK.md` remain historical evidence.
Backend/auth/session/rate-limiter code, nginx, migrations and hosted data are
unchanged. No live email, Google, model or analytical-data call was made. Local
isolated success does not replace the next GitHub run.

## Human checkpoint

Commit the reviewed follow-up on `codex/p05-opal-shell` and push to existing PR
#42. Wait for every check before merge; do not create a replacement PR or deploy
while CI is red. Existing frontend-only rollout/rollback instructions still apply
after merge. Keep the schema-3 backend and disabled activation flags.
