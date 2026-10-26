# P05 CI repair — October 26, 2026

The user authorized publishing this specific repair on a separate branch and
merging only after required GitHub checks pass. P06 remains on hold until it is
published and the required GitHub checks pass. The production application is
unchanged and healthy at its existing P05 frontend/P04 backend checkpoint.

## Problem and final behavior

The merged-main run failed with `browser_protocol_deadline` before recording its
first browser assertion. Its old seven-second timeout applied even to the first
command sent immediately after launching Chrome. It did not record the command
or retain the browser report. That evidence cannot prove retrospectively which
command stalled or whether cold startup was the cause.

Both browser gates now share a bounded anonymous-pipe transport. Exactly one
`Browser.getVersion` startup handshake may use up to 30 seconds; subsequent
commands retain seven-second limits. All commands share the existing overall
240-second deadline. There is no browser-journey or command retry.

Diagnostics contain allowlisted command/stage/reason/count/timing metadata.
They exclude parameters, evaluated expressions, URLs, raw frames, raw browser
errors and stream exceptions. Malformed, oversized, duplicate, unmatched and
wrong-session responses fail closed, as do pipe errors and pending-command
overflow. Legitimate navigation cancellation classification is preserved.

Cleanup now observes process termination and pipe drain, allowing one graceful
process-drain wait of at most five seconds within the remaining suite deadline.
The shutdown protocol command retains a one-second limit. A rejected shutdown,
forced kill, abnormal exit, unconfirmed cleanup or idle transport failure cannot
produce a passing gate. Normal explicit shutdown without a protocol reply is
accepted only after an observed zero exit with no signal. The original failure
diagnostic is preserved.

The earlier field helper fix waits for a visible, editable form field rather
than racing the protected auth-loading state. The failed classic run remains
recorded with its passing retest.

CI retains only JSON/PNG evidence in the four dedicated synthetic-fixture browser
directories, after success or failure, for seven days. It uploads no checkout,
arbitrary temporary directory, environment file, browser profile or fixture pipe.
The upload action is pinned to the verified commit for official
[`actions/upload-artifact` v7.0.2](https://github.com/actions/upload-artifact/releases/tag/v7.0.2).

## Verification

- 162/162 frontend unit/contract cases passed on Windows and again in a
  resource-limited Linux container with networking disabled. This includes 29
  deterministic transport regressions for cold/stalled startup, deadlines,
  malformed/replayed frames, redaction, pipe failures and abnormal cleanup.
- Both final synthetic browser suites passed 77/77 with no browser diagnostic,
  external requests or cleanup failure. The unchanged Opal/classic production
  assets were reused; browser profiles and loopback listeners were removed.
- Both final actual FastAPI/schema-3 browser suites passed 20/20, including
  session revocation, CSRF rejection, dataset denial and natural rate-limit
  recovery. Both report no browser diagnostic and confirm fixture resource
  removal with absence verified.
- Source and runtime-lock guards passed against the isolated candidate snapshot;
  new helper/test files were included in the source manifest.
- Actionlint 1.7.12, downloaded from its official checksum-verified release,
  accepted the workflow. External ShellCheck/Pyflakes integrations were disabled
  because those tools were unavailable; actionlint's workflow checks ran.
- Independent review found and then verified fixes for cleanup failure
  propagation. No blocking findings remained in that review.

The first strict-shutdown real Opal run passed all 20 assertions but failed its
one-second process-drain check. That failure is retained in
`opal-real-final/report.json`. It motivated the bounded graceful allowance and
deterministic delayed-normal-exit and stalled-exit controls; forced termination
still fails. Final reports are stored separately under `verified/`.

Local evidence: `.check-results/p05-ci-closure/` contains `unit.log`,
`linux-unit-verified.log`, and per-shell final browser reports. The synthetic source
snapshot and Linux evidence are in
`/srv/bank-ai/.check-results/p05-ci-closure-20261026-IG7ZiZ/`.
Earlier backend, installer, proxy and recovery results are recorded separately
in `P05_RELEASE_READINESS.md`; those suites were not repeated for this test-only
transport change.

## Configuration, migration and rollback

No new dependency, application setting, API contract, database migration,
backend change or production image is involved. Reverting the test-helper and
workflow changes restores the prior test harness; preserve the deployed
application and schema 3. A server restart cannot publish these GitHub checks.

Changed files are the shared browser-pipe helper and its regression suite, the
two P05 browser entry points, `.github/workflows/checks.yml`, and the current
checkpoint/verification records in `CLAUDE.md`, `README.md`, both handoff copies,
`P05_RELEASE_READINESS.md` and this document. Application frontend/backend,
authentication, dependencies, migrations and nginx are unchanged.

## Publication gate

The GitHub integration denied an Actions rerun with HTTP 403. Browser control
also stopped because it could not verify the active Windows browser URL; no
further UI input was issued. Neither condition is fixed by changing application
code. The historical failed run remains failed until GitHub executes a passing
run; local success is not a substitute for that remote result.

The repository's default `CLAUDE.md` rule reserves commits, pushes and PR creation
to the human maintainer. On October 26 the user explicitly authorized an exception
for this reviewed test/CI/docs repair: commit on a separate branch, publish a PR,
and merge only after required checks pass. Opening the repair PR triggers the
normal workflow without needing manual Actions-rerun permission. Other Git work
retains the existing human checkpoint.

## Prepared PR description

Title: `fix(ci): bound browser startup and preserve failure evidence`

The P05 browser gate could time out without identifying the stalled command,
and some abnormal browser shutdowns could be reported as successful cleanup.
Share a bounded, fail-closed transport between both browser suites, allow one
cold-start handshake within the suite deadline, reject abnormal cleanup, and
retain sanitized synthetic reports in CI. Preserve all existing application
security assertions and the auth-field readiness fix.

Validation: 162 frontend cases pass on Windows and offline Linux, both synthetic
browser suites pass 77 checks, and both real-database browser suites pass 20
checks with complete cleanup. Source/lock guards and actionlint pass. The
required remote CI outcome must accompany publication. No application/database
migration or deployment is required.
