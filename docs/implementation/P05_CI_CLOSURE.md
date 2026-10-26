# P05 CI and dependency repair — October 26, 2026

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

Chromium can return a root-generated missing-session error after a targeted
Fetch command loses its session during shutdown. A narrow exception preserves
that rejection only for the exact correlated shutdown error; explicit wrong
sessions, missing IDs, success payloads and malformed responses still fail.
Final verdicts also check late interception errors after cleanup. See the
[Chromium implementation](https://chromium.googlesource.com/chromium/src/+/lkgr/content/browser/devtools/devtools_session.cc).

The earlier field helper fix waits for a visible, editable form field rather
than racing the protected auth-loading state. The failed classic run remains
recorded with its passing retest.

CI retains only JSON/PNG evidence in the four dedicated synthetic-fixture browser
directories, after success or failure, for seven days. It uploads no checkout,
arbitrary temporary directory, environment file, browser profile or fixture pipe.
The upload action is pinned to the verified commit for official
[`actions/upload-artifact` v7.0.2](https://github.com/actions/upload-artifact/releases/tag/v7.0.2).

## Runtime audit finding

The first repair run, [40406128810](https://github.com/drewUTSA/Aqua/actions/runs/40406128810),
stopped at the runtime dependency audit: `opentelemetry-api 1.45.0` is affected by
[CVE-2026-114603 / GHSA-xcq7-p3pf-p88h](https://github.com/open-telemetry/opentelemetry-python/security/advisories/GHSA-xcq7-p3pf-p88h).
The lock now selects the maintainer's patched `1.45.1`, changing only that version
and its two hashes. Published PyPI metadata verifies the hashes and unchanged
Python/typing-extensions requirements; existing direct ranges remain satisfied.
The fresh patched-lock audit reports no known vulnerabilities.

`tools/checks/telemetry_probe.py` reproduces the old exposed parser entry using a
sentinel, avoiding vulnerable regular-expression work. The new runtime rejects
oversized single/combined headers before that entry, preserves exact boundary
behavior and recovers on valid headers. Inputs are capped at 8,193 bytes, and the
exercise runs in resource-limited containers with networking disabled. CI runs
the guarded probe against the built runtime image.

## Verification

- 170/170 frontend unit/contract cases passed on Windows and again in a
  resource-limited Linux container with networking disabled. This includes 37
  deterministic transport regressions for cold/stalled startup, deadlines,
  malformed/replayed frames, redaction, pipe failures and abnormal cleanup.
- Both final synthetic browser suites passed 77/77 with no browser diagnostic,
  external requests or cleanup failure. The unchanged Opal/classic production
  assets were reused; browser profiles and loopback listeners were removed.
- Both final actual FastAPI/schema-3 browser suites passed 20/20, including
  session revocation, CSRF rejection, dataset denial and natural rate-limit
  recovery. Both report no browser diagnostic and confirm fixture resource
  removal with absence verified. These final runs used the patched runtime.
- Source and runtime-lock guards passed against the isolated candidate snapshot;
  new helper/test files were included in the source manifest.
- Actionlint 1.7.12, downloaded from its official checksum-verified release,
  accepted the workflow. External ShellCheck/Pyflakes integrations were disabled
  because those tools were unavailable; actionlint's workflow checks ran.
- Independent review found and then verified fixes for cleanup failure
  propagation. No blocking findings remained in that review.
- The patched runtime passed all 1,056 distinct backend cases across both
  fixtures, synthetic restore/security fences, and the disposable installer's
  repeated migration, SCRAM, DDL denial/recovery and export checks. Its image is
  `sha256:9578f8882f88201f5753f64eb1ee477f5a7724c786e3ec9618130f56cf4f9771`.
- The old/new telemetry probes confirmed exposed/guarded parser entry with
  normal-header recovery; the new lock passed a fresh advisory audit with no
  known vulnerabilities. Black and Ruff passed all 148 checked Python files.

The first strict-shutdown real Opal run passed all 20 assertions but failed its
one-second process-drain check. That failure is retained in
`opal-real-final/report.json`. It motivated the bounded graceful allowance and
deterministic delayed-normal-exit and stalled-exit controls; forced termination
still fails. A later run identified the documented sessionless shutdown error;
that failure is also retained. Final patched reports are stored separately under
`final-patched/`.

Local evidence: `.check-results/p05-ci-closure/` contains `unit.log`,
`linux-unit-final-patched.log`, and per-shell final browser reports. The synthetic source
snapshot and Linux evidence are in
`/srv/bank-ai/.check-results/p05-ci-closure-20261026-IG7ZiZ/`.
Earlier backend, installer, proxy and recovery results are recorded separately
in `P05_RELEASE_READINESS.md`. The telemetry patch expands this repair to the
runtime lock, so the patched image receives fresh backend, installer/recovery
and actual-database browser checks rather than inheriting old results.

## Configuration, migration and rollback

No new dependency, application setting, API contract or database migration is
introduced. One existing transitive dependency is patched. After required checks
and merge, recreate only the backend using the tested patched runtime, preserving
the private-storage overlay, schema 3, current sessions and disabled activation
flags. The frontend image and Cloudflare configuration do not need replacement.
Use maintenance or a forward fix for an application regression; do not restore
the vulnerable dependency as rollback. Test/workflow changes can be reverted
independently. A server restart cannot publish the GitHub checks themselves.

Changed files are the shared browser-pipe helper and its regression suite, the
two P05 browser entry points, `.github/workflows/checks.yml`, the runtime lock,
the bounded telemetry probe, and the current
checkpoint/verification records in `CLAUDE.md`, `README.md`, both handoff copies,
`P05_RELEASE_READINESS.md` and this document. Application frontend/backend source,
authentication, migrations and nginx are unchanged.

## Publication gate

The GitHub integration denied Actions rerun and PR creation with HTTP 403. Browser control
also stopped because it could not verify the active Windows browser URL; no
further UI input was issued. Neither condition is fixed by changing application
code. Native Git authentication successfully published the branch, and its
existing credential was used only in memory for the authorized GitHub API call
creating [PR #43](https://github.com/drewUTSA/Aqua/pull/43). No credential was
printed or saved. The normal PR workflow provides remote verification;
local success is not a substitute for that result.

The repository's default `CLAUDE.md` rule reserves commits, pushes and PR creation
to the human maintainer. On October 26 the user explicitly authorized an exception
for this reviewed test/CI/docs repair: commit on a separate branch, publish a PR,
and merge only after required checks pass. Opening the repair PR triggers the
normal workflow without needing manual Actions-rerun permission. Other Git work
retains the existing human checkpoint.

## Prepared PR description

Title: `fix: repair browser CI and patch telemetry dependency`

The P05 browser gate could time out without identifying the stalled command,
and some abnormal browser shutdowns could be reported as successful cleanup.
Share a bounded, fail-closed transport between both browser suites, allow one
cold-start handshake within the suite deadline, reject abnormal cleanup, and
retain sanitized synthetic reports in CI. Preserve all existing application
security assertions and the auth-field readiness fix. Patch the audit-blocked
telemetry API from 1.45.0 to 1.45.1 with verified hashes and add a bounded offline
oversized-header denial/recovery probe.

Validation: 170 frontend cases pass on Windows and offline Linux, both synthetic
browser suites pass 77 checks, and both real-database browser suites pass 20
checks with complete cleanup. Source/lock guards and actionlint pass. The
required remote CI outcome must accompany publication. No database migration is
required; the backend runtime is updated after passing checks and merge.
