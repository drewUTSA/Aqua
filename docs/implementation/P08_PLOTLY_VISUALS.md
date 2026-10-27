# P08 Plotly and conditional visuals

Status: P08 is complete and deployed at code checkpoint `d76be9a` (PR #50),
schema 5. Required PR/main CI and production verification passed. The final
release record below supersedes the pre-release preparation status; P09 requires
a new user request and has not started.

The user authorized P08 after confirming the completed P07 release. Scope is a
lazy, bounded Plotly renderer and on-demand conversation/visual split, linked
result selection, chart/table controls, keyboard divider, close/reopen, compatible
zoom preservation and mobile navigation. Preserve existing account authority,
request IDs, lifecycle, exact numeric sidecars, safe exports and current mail
activation. P09 Settings and later phases remain excluded.

Use declarative allowlisted descriptors and validated data; never pass model
objects, HTML, executable callbacks, URLs or arbitrary Plotly configuration to
the engine. Unknown units, source freshness, aggregation and filters stay unknown.
Oversized or numerically unsafe plots retain exact table access with an honest
explanation. Plotly must stay out of sign-in and text-only initial loading.

Required evidence includes numeric/timezone/missing/negative/zero references,
stale/cross-chat/revoked selection, failed update retention, slow/racing render
cleanup, keyboard/reduced-motion/resize and mobile behavior, bounded bytes/points,
CSV formula defenses, both shells, actual browser/database journeys, dependency
and bundle checks, scoped red/blue regressions, PR/main CI and ordinary production
health/asset verification. Use synthetic disposable fixtures and fake providers;
no live analytical data, model exercise, new entitlement or private backup export
is authorized merely by this test scope. Any needed new migration/backup must
follow its reviewed gates. Record actual results here before claiming completion.

## Implementation and compatibility

Successful workspace results add a closed `presentation` version-1 sidecar.
The legacy `/api/query` response and P07 `result_metadata` version 1 stay intact,
including exact-decimal sidecars and their whole-result chart suppression.
No database migration, new role, entitlement or application secret is required.

The server chooses `text`, `explicit` or narrow visual `followup` intent using
the submitted question and already authorized context. One bar/line descriptor
may reference the result table; it contains axis keys, proven series units,
all row indices, a compatibility digest and explicit missing/reduction bounds.
The browser validates its closed keys and data, then constructs fresh local
Plotly inputs. It never accepts a layout, callback, template, URL or engine
configuration from a response. Recharts and its unused dependencies are removed.

Chart limits are 50 categorical bar rows or 500 total series points, including
missing slots, with at most two series sharing a proven unit. Charting never
samples, silently aggregates, fills a missing value or rounds an exact sidecar.
Unsupported shape, duplicate axes, naive/mixed timestamps, ambiguous multi-unit
series, excess points and exact values use the authorized table. Aware instants
are normalized to UTC in fresh chart coordinates; exported original values stay
unchanged. Calendar dates remain dates. Source freshness remains distinct from
result completion time, and unspecified SQL aggregation/filters remain unknown.
Compound calendar periods are explicitly labeled ordered categories; absent
periods are not invented or spaced as elapsed time. Table display and clipboard
preserve complete timestamp strings, including offsets. Unknown currencies use
plain numbers, while declared currencies keep their original units.

Plotly basic is pinned to **4.1.2**, with no transitive dependencies. The basic
engine loads only for a chart; built-in modebars, cloud sharing, links, editing
and MathJax are disabled. Zoom, Pan and Reset use fixed application-owned inputs.
See the [official release](https://github.com/plotly/plotly.js/releases/tag/v4.1.2),
[basic bundle documentation](https://github.com/plotly/plotly.js/blob/v4.1.2/dist/README.md)
and [pinned configuration definition](https://github.com/plotly/plotly.js/blob/v4.1.2/src/plot_api/plot_config.js).
Those defaults matter because Plotly 4 otherwise offers cloud sharing.

View state contains bounded IDs and interaction flags, with payloads derived
from the currently authorized conversation. A stable local view ID survives
first-message canonicalization. Request/client/reply identity fences updates;
ordinary text cannot replace a visual or reopen a dismissed pane. Failed
updates retain the selected result with an honest status and retry action.
Grant loss, unavailable results, deletion and account/chat ownership changes
synchronously remove the visible payload; chart disposal fences late imports
and draws, disconnects observation and purges the engine node.

Desktop starts around 38% conversation / 62% visual, constrained to usable widths.
The divider supports pointer, arrow keys, Home/End and a numeric device-only
width preference. Available container width, including sidebar changes, chooses
the mobile layout. Conversation/Visuals tabs appear only for an active visual;
readiness never switches tabs. Owned tab DOM and scroll positions survive tab
changes, and the composer stays available in either view. Chart/table toggles
retain compatible zoom; query/source/axis/period/unit changes reset it with a
visible explanation. Close returns focus to the result action or composer.

## Verification record before release

The actual candidate backend is
`sha256:99827d3498aa20d997fd2811104a300c1dce11d188238259985a67b4ce6c0aff`.
Its 116 runtime source files match the reviewed source; dependency installation,
privacy/telemetry probes, pinned dependency audit, installer checks, schema-5
restore proof and cleanup passed. The canonical two-fixture matrix passed all
**1,303 unique cases**: bank 1,284 passed / 19 fixture-specific skips; Pagila
1,291 passed / 12 fixture-specific skips. Every case ran in its applicable
fixture. This includes 37 presentation and 23 independent adversarial cases.
No model, analytical database, real email recipient or production data was used.

Final frontend build `r6` passed **323/323 unit tests**. Each secure shell passed
103 synthetic browser assertions, 39 real private-database assertions and
35 actual Plotly/private-database assertions. The dedicated visual run used
exactly 12 fixed fake jobs per shell, one active execution at most, and observed
zero external/provider calls, runtime errors, console leaks or protocol errors.
Every browser profile, loopback listener and disposable backend resource was
removed, with resource absence confirmed. These are independent fresh runs,
not historical P07 results.

The actual Plotly runs cover literal hostile labels, zero/negative/missing
values, real drag zoom, compatible tab/scroll retention, changed-query reset,
bounded keyboard resizing, 320/740px controls, mobile readiness without a tab
switch, close focus/purge, failed update retention/retry, native formula-safe
copy/CSV, UTC coordinates with original timestamp table/copy values, unknown
currency, exact-value and 51-bar fallbacks, polite explanation after dismissal,
grant-revocation purge without navigation and confirmed logout. Active Zoom
text contrast measured 11.55:1. Final screenshots were visually inspected.

Nested table validation now rejects malformed metadata/cells and excess bounds
with an honest unavailable state, preserving original objects and exact-cell
provenance for valid data. A malformed legacy chart title/series falls back to
its table. Neither path can hand arbitrary configuration to Plotly.

The final lazy engine is 1,211,596 bytes / 404,238 gzip bytes and remains outside
the initial graph. Initial Opal JS/CSS adds 11,027 gzip bytes versus P07. Both
manifest/bundle checks passed. Both exact frontend images matched all five
public assets, and each passed the isolated proxy's 116-request denial/recovery
gate with 51 admitted work calls and confirmed cleanup. The public-asset image
packaging explicitly sets readable public-file modes; private volumes and
runtime permissions are outside that packaging context.

Red/blue evidence includes the corrected table-column `fractionDigits` boundary,
offset timestamp normalization, a deterministic dropped-control/resize race,
an actual polite-explanation pane-reopen reproduction, and original formatter
proofs for invented USD and truncated timestamps. Final regressions pass.
Intermediate browser failures caused by harness syntax/waiter/teardown errors
are recorded as harness failures, not product vulnerabilities.

Source/lock checks, Black (238 Python files with the two documented existing
exclusions), Ruff (240), 32 standalone fixture checks, dependency audits and
actionlint passed. The final 53-file reviewable change set passed the canonical
redacted source scanner. PR/main checks and production verification were pending
at this pre-release stage; the final release record below supersedes that
status. Intermediate builds are not release evidence.

The tracked [verification record](evidence/p08/verification.json) contains
sanitized counters, report hashes and immutable image identities. Detailed local
evidence is under `.check-results/p08/`, `.check-results/p08-backend-intent/`,
`.check-results/p08-security-audit/` and `.check-results/p08-release/`.

## Final release evidence

[PR #50](https://github.com/drewUTSA/Aqua/pull/50) merged at code checkpoint
`d76be9a5e3136806cdc48dc16e11607c2286371c`. Required
[PR CI](https://github.com/drewUTSA/Aqua/actions/runs/40443052497) and
[merged-main CI](https://github.com/drewUTSA/Aqua/actions/runs/40444105566)
each passed all 27 steps. The separate
[production record](evidence/p08/production-release.json) contains sanitized
deployment, delivery and browser evidence. The earlier
[verification record](evidence/p08/verification.json) remains the pre-release
local-check snapshot.

Production passed verification at **10:50:14 p.m. CDT on October 26, 2026**
(03:50:14 UTC on October 27). Only the backend and Opal frontend were recreated,
using the exact tested immutable images:

- Backend: `sha256:99827d3498aa20d997fd2811104a300c1dce11d188238259985a67b4ce6c0aff`.
- Opal: `sha256:8ffd49a31d62e7577455f6784d772b8e1a0d9bb0195ab9b860aa62826a1d02a1`.

Both are healthy at schema 5. P08 needed no migration, DDL or new private-data
export. Database identity and private data/socket volumes were preserved, as
were the environment and four active password-login, registration, recovery and
account-mail flags. The provider key remains absent from the web process. The
private worker file, scheduled cron entry and protected launcher lock were
preserved. A passive check observed the scheduled worker naturally idle at
03:51:02 UTC, with cron active and the exact managed line/lock intact; the probe
triggered no mail.

Eight bounded public route checks passed: `/`, `/signin` and `/api/health`
returned 200; unauthenticated account/chat and fixed analysis-request/event
probes returned 401; public `/api/ready` returned 404. All five origin files
match the frozen tested frontend. Four public hashed assets match their origin
bytes, including the lazy Plotly engine. Public HTML is the exact origin HTML
plus one pre-existing 367-byte Cloudflare Web Analytics script insertion, whose
SHA-256 is `2765a11d900a367f5d9d2bb378ddeef7eb25852fe48aa9b2bbd2824f9cb7a284`.
Removing only those pinned bytes yields the exact origin hash; the raw public
HTML hash differs. Cloudflare documents this
[automatic script injection](https://developers.cloudflare.com/web-analytics/faq/).

Two initial attempts safely rolled back to healthy P07. The first reported only
a generic redacted deployment/verification failure; the instrumented second
confirmed a public-asset hash mismatch. Diagnosis identified that the verifier
expected public HTML without the existing edge insertion; only the ignored
operator verifier changed.
Twelve HTML-byte checks (including ten rejection cases), 15 offline
deployment/rollback scenarios and privacy cases passed, followed by independent
review. No product or Cloudflare setting was
changed to accommodate the verifier.

A fresh anonymous Chrome check loaded the new JS/CSS, showed enabled email and
password fields plus registration/recovery links, and made no initial Plotly
engine request. Its screenshot was reviewed; the browser and profile were
cleaned up. No authenticated account, dataset grant, live model/analytical
request or new mail recipient was used. Isolated actual-database Plotly journeys
above establish the chart interactions; the public check establishes delivery
and the unauthenticated entry flow.

Local production evidence is in
`.check-results/p08-release/production-deployment.json` and
`.check-results/p08-release/public-browser.json`. P00–P08 are complete and live.
P09 Settings requires a new user request; P09 through P13 have not started.

## Deployment and recovery

After reviewed PR and merged-main checks pass, recreate only the backend and
frontend from the exact tested immutable images. Preserve schema 5, the existing
database container and both private volumes, activation flags, worker environment,
owner-only directories, cron and launcher lock. Do not run database DDL, export
a fresh private backup, stop mail, change Cloudflare configuration or restart
unrelated services for this compatible renderer release.

The tested P07 backend image is
`sha256:81acee49864b4c08ba400fdc41b512b03b3dcacdafc6c7df5dc8e990247845e7`;
the previous secure Opal frontend is
`sha256:d86a8f577c7744ce85145e9359880618082deaa9eb7959250585a20efce73c9f`.
Both remain compatible with schema 5 and table/exact-value access. Roll back
those images without reverting the database if release health checks fail.
P09 through P13 require the user's next phase request.
