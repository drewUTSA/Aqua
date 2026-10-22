# P05 handoff follow-up: reversible shell and complete navigation

Status: final run 3 passed all local gates: 120 unit cases and, for each shell,
77 synthetic browser checks plus 20 real-backend browser checks. Both image
builds and exact-asset rebuild comparisons passed after the last contrast fix.
Evidence is sealed; copy/hash guards verify the actual checkout before human
review. Measurements below describe run 3, now committed in PR #42; the later
[fixture CI correction](P05_CI_FIX.md) has its own evidence and review checkpoint.
Neither shell is merged or deployed. This record supersedes the
earlier P05 readiness conclusion. Previous evidence is retained separately from
the current results below.

## Why the follow-up is required

The handoff's P05 exit explicitly requires a UI feature flag that can restore the
prior shell while keeping secure authentication and password-only access. The
first P05 implementation had no presentation flag. Its proposed P04-image rollback
did not satisfy that requirement once password accounts were enabled. The audit
also found that legal navigation could unmount the account owner while logout
was unresolved, and that title search and some viewport/delivery acceptance
evidence were missing. These are implementation gaps, not optional phase work.

## Presentation-only rollback

The supported build-time setting is `VITE_AQUA_UI_SHELL=opal|legacy`:

- `opal` is the default approved charcoal/opal presentation with subtle specks.
- `legacy` restores the classic blue/glass presentation and bottom-composer
  arrangement using the same maintained semantic components.

Docker exposes `ARG AQUA_UI_SHELL=opal`; Compose forwards `AQUA_UI_SHELL`, default
`opal`. Invalid values fail the build instead of silently selecting a shell. The
build passes the chosen value to Vite and still forces both production demo
flags off. Local `.env` files remain excluded from the Docker context.

This is a build selection, not a runtime preference, URL parameter, cookie or
browser-storage value. Rebuild/redeploy the frontend to change it. P09 will own
supported end-user appearance preferences; this operator rollback does not
implement them.

Both variants share Workspace ownership, the semantic composer, native mobile
dialog, account menu, authentication hook, fixed routes and canonical account
fence. The current dual-login, verification/recovery, CSRF, one-POST/cooldown,
privacy-lock and revocation behavior remains in both variants. Legacy does not
restore the obsolete authentication flow or the WebGL composer implementation.
The visual rollback cannot change server feature flags, permissions, secrets,
session limits, email budgets, database state or the active backend image.

## Navigation, search and policy corrections

An existing authenticated account owner stays mounted behind a public legal page.
Its private workspace remains hidden/inert while logout is pending or failed;
Back returns to the appropriate locked or authorized state without losing the
draft. Confirmed logout or account change still discards private state. A direct
signed-out visit to a policy page remains public and performs no authentication
bootstrap merely to display the page. Settings policy links use the local SPA
navigation path to preserve the owner instead of causing a reload.

The sidebar includes accurately labeled visit-local title search. Input is at
most 120 characters, at most 100 conversations are considered and at most 512
characters of each title are compared. Search reads page-local titles only;
it makes no API/model/database request and does not search message bodies or
promise refresh-safe history. Empty/no-match/clear states are real controls.
The conservative worst-case bound is O(C × T × Q) for substring matching, with
C <= 100, T <= 512 and Q <= 120. Future durable search belongs to P06 and must use
owner-scoped queries and measured index/pagination plans.

Policy text is corrected to describe private account/session storage, password
hashes when enabled, account email, configured model/embedding processing and
visit-local chat memory. Factual implementation corrections are not legal or
operator approval. Full policy/contact/retention review remains LAUNCH-10/P13.

## Handoff requirement and evidence matrix

References below use the original `AQUA_CODEX_HANDOFF.md` line numbers and named
acceptance IDs, preserved as an immutable specification. The table distinguishes
P05 evidence from future phase obligations rather than treating every handoff
row as complete.

| Requirement/reference | Current implementation or correction | Required evidence and current status |
| --- | --- | --- |
| P05 prepare, line 214 | Approved Opal assets/tokens, complete responsive composer/sidebar, explicit access/workspace/legal/404 routes, separate identity and dataset capability | Both shells' source/route review and build/synthetic browser checks passed |
| P05 verification, line 218 | Real auth journeys, no-dataset account UI, no empty pane, failed-query draft recovery and production demo disabled | Both synthetic/actual-backend suites and environment-canary builds passed |
| P05 exit/rollback, line 220 | `VITE_AQUA_UI_SHELL=opal|legacy` / Docker `AQUA_UI_SHELL`; same secure auth and password-only access in both | Both exact images built/tested, invalid values rejected, shared auth UI and actual-backend journeys passed |
| UI-01, line 1370 | Opal-black/charcoal/pearl presentation, local Figma assets, static specks, system font fallback | Representative desktop/tablet/mobile screenshots visually reviewed; legacy intentionally preserves prior direction; passed |
| UI-02, line 1371 | Chat-only first login/New Chat with no reserved visual pane; composer anchored below readable conversation | Both variants passed desktop, tablet, intermediate and narrow-width checks |
| UI-03, line 1372 | New Chat, bounded visit-title search, recents, curated prompts, model choice and account controls; unavailable projects omitted | Search ownership/no-network/no-match/clear, long-label/draft/IME/newline/send checks passed in both |
| UI-04, line 1373 | Viewport-contained account menu and Settings return; shared owner retains draft/scroll | Keyboard/outside/focus and Settings/legal/Back checks passed; scroll was 80 before and 80 after navigation in both |
| UI-05, line 1374 | Authenticated no-dataset account can use account UI but cannot query | Browser no-query/Settings/sign-out and actual API 403 passed in both variants |
| AUTH-01, line 1353 | Independent supported GIS and password forms; labels, show/hide, paste/autofill/managers | Both forms' desktop/mobile/keyboard and actual-backend synthetic-identity journeys passed |
| AUTH-02, line 1354 | Safe validation/pending/credential/provider/throttle states, duplicate prevention | Generic-failure/provider/no-replay and actual natural Retry-After recovery passed in both |
| AUTH-04, line 1356 | Email-first registration and mailbox proof; no client-created verified badge/grant | UI/proof and actual private-DB/captured-mail journeys passed. P04 server concurrency/denial evidence remains |
| AUTH-05, line 1357 | Generic reset request, fixed trusted link path, bounded mail behavior | Synthetic/actual captured-link recovery journeys passed. P04 recipient/global allocations remain |
| AUTH-06, line 1358 | Server-confirmed reset, one-use proof, session revocation and normal sign-in | UI proof/reset-ambiguity/cross-tab plus actual old session/password denial and new-password success passed |
| AUTH-07, line 1359 | Canonical identity gate and safe fixed-route navigation | Browser account switching, hostile destinations/legal detours and actual session restoration passed |
| AUTH-09 current-session portion | Shared hidden/inert owner survives pending/failed sign-out across legal navigation | Held/failed logout -> policy -> Back retains locked draft; confirmed callback clears it; browser checks passed. All-session management remains P10 |
| A11Y-01, line 1428 | Semantic controls, focus containment/return, labeled status/errors and safe forced-color icons | Keyboard/forced-colors/reduced-motion passed in both; scoped contrast reviewed; not a full screen-reader certification |
| A11Y-02, line 1429 | Responsive drawer/composer and flexible text layout | Desktop, 1024x768, 768x1024, 320px, 390x420 keyboard height and 200% landing/active/auth text passed |
| PERF-01, line 1432 | Local static assets, lazy chart chunk, bounded response and history work | Recorded asset/gzip sizes, no chart chunk at login and local timing samples below; no production latency/capacity claim |
| LAUNCH-02, line 1441 | Reachable mobile composer instead of an unrelated marketing sticky CTA | Shortened-height and safe-area checks passed with focus/controls reachable |
| LAUNCH-12, line 1451 | Local SVG assets and lazy noncritical chart delivery | Build delivery sizes and local timings recorded; legacy-only workspace logo cost disclosed below |
| P05 security row, line 1539 | Same server boundaries; shared routing/account ownership across shells | Hostile UI content/redirects, account/logout privacy and actual server CSRF/revocation/cooldown checks passed in both |
| Phase checkpoint, lines 148–158 | Scope review, tests, paired red/blue evidence, quality, docs and human checkpoint | Evidence hashes sealed and protected files unchanged; copy/hash guards verify the actual checkout. Remote CI follows human push; no agent commit/PR |

## Follow-up verification ledger

Current reports are sealed under `evidence/p05/rollback/`. The previous
117-unit/56-synthetic/16-real-browser pass and old image digest remain historical
baseline evidence only. Current unit/contract checks passed **120 cases**; the
12 fixture cleanup regressions, Black (145 Python files), Ruff, source guard and
runtime-lock checks passed. Both explicit production rebuilds byte-match their
tested image assets. The 16 protected-file hashes are unchanged; copy/hash
verification against the actual checkout is required before human review.

| Gate | Opal | Legacy |
| --- | --- | --- |
| Build with allowed shell and production demo off | Passed; canary excluded, invalid shell rejected | Passed; canary excluded, invalid shell rejected |
| Exact-image synthetic UI/security/browser suite | 77 passed; 216 requests/101 API | 77 passed; 229 requests/101 API |
| Real FastAPI/schema-3 PostgreSQL browser and natural cooldown | 20 passed; 121 requests/66 API, 70.72 s | 20 passed; 127 requests/66 API, 71.48 s |
| Auth routes and password-only account access | Synthetic and real passed | Synthetic and real passed |
| Failed logout through legal/Back preservation | Passed | Passed |
| Bounded visit-local search and account clearing | Passed | Passed |
| Tablet/intermediate/keyboard-height/200% text and visual review | Passed | Passed |
| Delivery bytes and initial/lazy asset observations | Recorded; login defers chart chunk | Recorded; login defers chart chunk |
| Browser/profile/listener/backend cleanup confirmed | Passed; no remaining backend IDs | Passed; no remaining backend IDs |

Both synthetic runs recorded zero external attempts, console bearer leaks,
runtime/protocol errors and forbidden API calls. They used the assets extracted
from these built-but-not-deployed images:

| Shell | Image digest |
| --- | --- |
| Opal | `sha256:ef5b096f38e4b0b63d2247cb19aed613de0cb6d664a570ace0d73ae423e03aeb` |
| Legacy | `sha256:a363a8b0768c9e3b7a7334d20eebac9be9186bc97d15d340ac79fd8dd8c3cb58` |

Both images were built from context SHA-256
`139b297690bf0bb17b6eb480f70b055ccfa0baec4aaae9f688a14780b4cb2937`.
Build containers and temporary contexts were removed. Browser reports carry
loaded-asset hashes to bind results to the appropriate image.

Both actual-backend runs also recorded zero external attempts, console bearer
leaks and browser/protocol errors. Legacy recorded two canceled navigation requests
in the real run and one canceled interception in the synthetic run; none produced
a protocol error. Each real journey verified the genuine
Retry-After wait and zero automatic password retries, followed by the old-password
401 and new-password 200. Synthetic accounts use actual FastAPI and disposable
schema-3 PostgreSQL; Google verification and outgoing email transport are fake.
Two explicit fixture-clock steps separate other scenarios, while the tested
cooldown waits naturally. Both backends reported removal and absence confirmed
with `remaining_ids: []`, in addition to browser/profile/listener cleanup.

The final guard must also verify protected files and the copied source. A mocked
API rejection proves browser handling, not server enforcement. Real backend fixtures
use synthetic accounts, fake Google verification and captured email, with no
production database/provider/model traffic. The genuine cooldown test must wait
the server's Retry-After, make no automatic credential/email retry and demonstrate
normal recovery afterward. No failure may be relabeled as a pass.

Initial-login delivery checks require at most three JavaScript requests and
600,000 decoded JavaScript bytes, at most 80,000 decoded CSS bytes, and no
`DashboardPreview` chart chunk. Both variants passed these budgets. Delivery
measurements are:

| Asset/sample | Opal | Legacy |
| --- | --- | --- |
| Main JavaScript decoded bytes | 440,078 | 440,080 |
| Main JavaScript local gzip bytes | 136,078 | 136,080 |
| CSS decoded/local gzip bytes | 48,503 / 10,454 | 48,503 / 10,454 |
| Lazy chart decoded/local gzip bytes | 407,228 / 110,277 | 407,228 / 110,278 |
| Legacy logo decoded/local gzip bytes | Packaged but not requested by Opal workspace | 2,111,901 / 329,472; requested only in legacy workspace |
| Local desktop sign-in navigation sample | 97.7 ms | 89.0 ms |
| Local desktop workspace navigation sample | 41.4 ms | 36.3 ms |
| Local mobile workspace navigation sample | 23.5 ms | 72.2 ms |
| Local mobile sign-in navigation sample | 37.2 ms | 29.3 ms |

Gzip figures use the extracted asset bytes and deterministic local gzip; they
are not an assertion about deployed transfer encoding. The legacy artwork is a
material delivery cost retained for the classic presentation. It is not loaded
on login or in Opal workspace. Some first-paint/first-contentful-paint fields were
unavailable (`null`); they are not zero. Timing samples are local loopback
observations, not production Core Web Vitals, statistical benchmarks or capacity
SLOs. The mobile keyboard check uses a shortened viewport; physical-device
keyboard/notch behavior and complete screen-reader coverage remain later release
checks. Safe-area style assertions cover all four insets.

## Retained findings and paired fixes

- **Legal navigation unmounted the account owner:** owner lifetime now spans
  public legal detours. Both pending and failed logout retain hidden/inert drafts;
  direct policy visits still avoid authentication bootstrap. Both regressions pass.
- **Hidden conversation geometry disturbed scroll restoration:** a hidden view
  reported zero dimensions and was treated as near-bottom. Suspension and visible
  geometry guards preserve the previous position; both final runs measured 80
  before and 80 after Settings return.
- **Short keyboard viewport and enlarged text obscured controls:** compact landing
  layout and active-conversation overflow rules keep the composer and account
  controls reachable. Both shells pass 390x420 and 200% landing/active checks.
- **Classic text/borders needed contrast adjustment:** conservative legacy muted
  text contrast is at least 4.65:1, with composer border above 3:1. Opal's earlier
  scoped palette checks remain applicable. These are not full accessibility claims.
- **Search text over the classic gradient:** final review found label/status
  gray could fall to about 3.5:1 at a brighter scrolled position. Those selectors
  now use the same `#c6e0eb` as the reviewed legacy copy. Both images, synthetic
  suites, actual-backend suites and exact-asset rebuild comparisons passed after
  this final color-only correction. Classic desktop/keyboard views were reviewed.
- **Harness serialization and CSS-rule traversal assertions failed:** the checks
  were corrected to inspect the actual DOM/rule shapes. The failed reports remain
  in the findings record and the complete suites were rerun; no failure was waived.

The sealed evidence package uses `{shell}-synthetic-report.json`,
`{shell}-real-report.json`, `{shell}-image.json`, `summary.json`,
`retained-findings.json`, `quality-checks.json`, `local-checks.json` and `artifact-hashes.json` under
`evidence/p05/rollback/`; reviewed visual files begin `{shell}-synthetic-`.

## Operator build, deployment and recovery

These are reviewed commands for after the human merge/release decision, not a
record that they have been executed. Build tags distinguish the two variants:

```bash
docker build --build-arg AQUA_UI_SHELL=opal -t aqua-frontend:opal-p05 frontend
docker build --build-arg AQUA_UI_SHELL=legacy -t aqua-frontend:legacy-p05 frontend
```

For the project Compose deployment, retain the approved private-storage overlay
and the current schema-3 backend. To select the classic presentation, rebuild and
replace only the frontend:

```bash
export AQUA_PRIVATE_STORAGE_DIR=/home/ben2004/.aqua-runtime/app-storage
export AQUA_UI_SHELL=legacy
docker compose -f docker-compose.yml -f compose.app-storage.yml build frontend
docker compose -f docker-compose.yml -f compose.app-storage.yml up -d --no-deps frontend
```

Use `AQUA_UI_SHELL=opal` and the same frontend-only commands to return to Opal.
Before replacement, verify the merged source, candidate image digest and current
backend/schema/flag state. After replacement, verify only the frontend changed,
both origin routes remain correct, public readiness stays private, unauthenticated
API access is denied and the selected shell's shared auth routes load. Do not
exercise real mail or provider callbacks without their reviewed activation scope.

Do not use the old P04 frontend image as the P05 shell rollback once password-only
users exist. Do not downgrade the schema-3 backend, reapply bootstrap, loosen
permissions, enable registration/mail or modify the hosted analytical database.
An unexpected authentication regression requires maintenance or a compatible
forward fix. Full settings, durable history, jobs and Plotly remain P09, P06,
P07 and P08 respectively; production capacity/full launch testing remain P12/P13.
