# P09 Settings and safe preferences

Status: complete and deployed on October 28 at 21:58:59 UTC. PR #52 merged as `05accec31da7d257ca5f1ffb7bd4897eac70d8b5` after all required PR checks passed; the merged main checks and controlled production verification also passed. Canonical isolated results cover 1,385 backend cases, 399 frontend tests, both production builds and eight browser gates. Eight synthetic screenshots were visually reviewed. See the [isolated verification record](evidence/p09/verification.json) and [release record](evidence/p09/release.json). The separately requested homepage supplement is under verification; P10/P11 remain separate phases.

The October 28 continuation resumes the clean P08 closeout at `14993c2`. The
working change replaces the Settings placeholder with nine categories, local
search, a shared saved/draft/preview model and actual account/device preference
persistence. Authentication, analytical grants, bounded jobs, conditional visuals,
exact result data and the activated account-mail worker remain separate controls.

## Supported behavior

Account preferences include finite theme/accent, interface density, static specks,
surface and typeface presets; optional sidebar section visibility/order and
recent count; starter suggestions, nonessential timestamps and code wrapping; initial
result view, approved palette/legend/grid controls, compatible exploration,
table density/page size and display precision; expanded chart summaries; and
reviewed regional number/date/time formatting options. Interface language is
English. `en-US` and `en-GB` select regional formatting, not additional translated
interfaces. Timezone choices are device detection, UTC, America/Chicago,
America/New_York, America/Los_Angeles and Europe/London.

Device-only preferences include contrast, 100/112.5/125/150 percent text size,
reading spacing, sidebar state, conversation width, a bounded preferred split,
send shortcut, auto-scroll, chart/device motion and announcement verbosity.
Touch targets, visible focus, essential errors, basic chart text/table access and
the closed visual pane at New Chat are mandatory behavior under every preset.
Appearance changes do not submit or rerun questions, change source currency or
grant permission. An explicit requested chart/table takes precedence over the
initial result-view preference.

Settings categories retain one shared draft. Safe appearance changes preview
immediately; Cancel restores the last confirmed saved values. Reset section
preserves unrelated section edits; Reset all requires confirmation. Both reset
the draft only. Reset/import have their own undo snapshot; ordinary Cancel
restores saved values rather than the earlier unsaved draft. Leaving Settings
offers Save, Discard or Keep editing, including guarded browser navigation;
refresh/close uses the browser's supported unsaved-work warning.

The UI uses explicit account/device labels. A save freezes a submission snapshot,
prevents duplicate submission and confirms scopes independently. Account success
with a local-store failure retains the device draft, and the reverse retains the
account draft. Neither case reports a combined successful save. A late response
cannot acknowledge newer values. If a write response is lost, an authoritative
read checks the server revision before another write is offered. Authentication
checks suspend work; they do not silently rebase a dirty draft onto a newer
revision from another device. Logout/switch fences async completion and removes
the prior account's client drafts and bounded device preference cache.

The nine categories are Appearance, Workspace, Chat & AI, Charts & tables,
Accessibility, Notifications, Language & region, Account & security, and Privacy
& data. Categories whose operational services are later phases provide truthful
availability copy. Current account identity and the existing account-menu logout
remain reachable. No credential, notification permission or private-data
operation is performed by ordinary preference saves, resets or imports.

## Contract and storage compatibility

| Operation | Contract |
| --- | --- |
| Read | `GET /api/v1/me/preferences`, current authenticated owner only |
| Save | `PUT /api/v1/me/preferences` with `{schemaVersion:1, expectedRevision, values}`; `values` is the complete closed account snapshot |
| Success | `{schemaVersion:1, revision, values, capabilities}`; canonical values and a safe positive integer revision |
| Conflict | `409 revision_conflict`; retain the draft and require reload/review before overwriting a newer record |
| Future stored schema | `409 unsupported_schema`; preserve the row and block writes |
| Other failures | Fixed safe error envelope; 401 invalid session, 403 denied request, 422 invalid contract, 429 with `Retry-After: 60`, 503 unavailable storage/configuration |

There is no caller-supplied owner or dataset selector. Extra query parameters,
unknown/protected values, wrong types, incompatible versions, extra envelope
fields and incomplete account snapshots are rejected. The request path retains
same-origin/CSRF protection, bounded body parsing, safe validation errors and
`Cache-Control: no-store`. A current authenticated account may customize its own
preferences without an analytical dataset grant. The preference path never
invokes a model, analytical query, email provider or arbitrary network fetch.

Both reads and writes use the existing durable **60 operations per account per
minute workspace budget**, shared across relevant workspace actions, sessions
and workers. Admitted revision conflicts cannot roll back this accounting.
This deliberately avoids a new unbounded limiter table/key namespace. It also
means heavy workspace activity can temporarily throttle preferences; it is not
a measured availability or production-capacity guarantee.

The existing `app.user_preferences` table is reused. Identity creation already
creates a versioned account row; known missing preference keys are filled with
documented defaults. Unknown current-version fields/values or an unsafe stored
revision fail closed, preserving the raw record rather than silently discarding
choices on write. Revision compare-and-swap and authority checks occur in short
private-storage transactions. Applied migrations 0001–0005 are unchanged;
**schema 5 remains current**. No dependency, provider secret, role or migration
is added by P09.

Device values use the bounded owner-specific browser namespace
`aqua-preferences-device:v1:<canonical-owner>`. Future versions and unsupported
stored choices fall back to safe presentation while preserving the raw record
and blocking overwrite. Corrupt/unavailable local storage produces a recoverable
warning; a failed or silently ignored local write does not report persistence.
The store contains no identity attributes beyond its owner key, sessions,
credentials, private prompts, result data or recovery tokens. Confirmed logout
and account switching purge the prior owner's cache. Reloading the same signed-in
account preserves supported saved device preferences. Demo changes are explicitly
visit-only and do not call the preference endpoint or claim account/local sync.

## Portable import/export

Export downloads only last-confirmed saved values as
`{schemaVersion:1,account:{...},device?:{...}}`. Including device values is an
explicit choice; unsaved draft values are not exported. No identity, email,
credential, token, custom instruction, conversation, result, consent or permission
field is present. No export is triggered merely by saving a preference.

Import checks file size before reading and limits UTF-8 content to **64 KiB**.
A bounded JSON grammar pass rejects duplicate/escaped-duplicate object keys,
excess nesting and excess container cardinality before ordinary JSON parsing.
The closed schema then rejects unknown/prohibited keys, objects where scalar
choices are required, wrong types, unsupported enum choices and unsafe numeric
bounds. Omitted import keys leave the existing draft unchanged. Any invalid
field rejects the whole proposal without changing saved values, draft or preview.
Strings are data, never HTML, scripts, CSS, fetch URLs or permission grants.

A valid import displays a comparison grouped by account/device scope. Only Apply
to draft changes preview; Save is still required. Cancel import and Undo import
have distinct behavior. Device imports remain device-scoped. Server validation
and expected revision are enforced again when account values are saved.

## Explicitly unavailable capabilities

The response advertises false for account-security operations, notification
delivery, private data export/deletion, personal instructions, response style,
response language and a persisted default model. The existing model selector
continues to choose supported models for a question. This change does not
implement credential/profile changes, linked identities, recent-auth challenges,
session lists/revocation, subscription consent, browser notification permission,
quiet hours, sounds, history/account deletion or private data jobs. P10/P11 own
those operational capabilities. Partial-response streaming, code line numbers,
new language packs, a continue-last-chat start screen and remembered export
format are also not advertised as working preference controls.

## Security and recovery evidence map

| Boundary/hypothesis | Required check and defensive outcome | Evidence status |
| --- | --- | --- |
| Owner/CSRF/session enforcement | Direct forged owner/extra fields, foreign identity, missing/expired/revoked session and bad Origin/CSRF fail without unauthorized writes or provider work | `backend/tests/test_preferences_api.py`; passed in the canonical bank/Pagila matrix |
| Revision/schema safety | Two writers cannot overwrite a newer revision; future/corrupt records survive rejected writes | `test_preferences_repository.py`, `test_preferences_schema.py`; canonical matrix passed, including concurrent real database leases |
| Durable abuse accounting | Account/session churn and repeated admitted conflicts cannot evade the shared budget; cooldown recovers | API/repository regressions passed in the canonical matrix |
| Import/code injection | Oversized, duplicate-key, nested, prototype, script/CSS/URL-like, wrong-type and protected-key proposals leave the whole draft unchanged | `preferences-schema.test.mjs` passed in the complete 399-test suite; both final Settings browser gates also passed hostile-import cases |
| Async/partial success | Snapshot acknowledgements retain newer edits; either saved scope survives failure of the other; explicit conflict review preserves drafts | `preferences-state.test.mjs` passed in the complete suite; real Settings conflict/reload and workspace journeys passed in both shells |
| Actual UI context | Provider-backed Settings renders with separate undo data and callback; initial render cannot throw from a context-name collision | `preferences-render.test.mjs` passed in the complete suite; actual Settings renders and interacts successfully in both shells |
| Preference rendering | Supported workspace/chart/table choices preserve bounded results, exact source values, chart alternatives and New Chat pane behavior | Eight `preference-presentation.test.mjs` cases passed; both final actual-Plotly gates passed 37 assertions including explicit charts against the saved Table default |
| Keyboard/theme/reflow | Native dialog focus/Escape/return, mobile categories, reachable save, light/dark/accent/contrast, motion and forced colors | Each final Settings gate passed 41 assertions and 128 measured preset combinations; eight selected synthetic screenshots visually reviewed |
| Isolation and cleanup | Synthetic users, fake providers and disposable DBs only; cleanup proves no remaining test listener/profile/container/volume | Canonical backend/storage/proxy and every final browser gate confirmed owned-resource cleanup; no production container changes |

No historical P08 pass is a fresh P09 test. A build or SSR check is not a
substitute for real browser interaction, direct API/DB boundaries or the required
red/blue checks. Record failed intermediate attempts and their fixes/retests.

## Final verification record

The canonical backend package is
`p09-checks-20261028204419094-9e42e937`, source archive SHA-256
`719f0719c34d8ae9f720d1612c76b2f65f960587a44f5c1062e603cbbe94991d`.
Its immutable candidate is
`sha256:5ff0cb141a3399f95458cc20fcadfbe66577e750702fd74ba6238716d7c99897`.
All **119 installed runtime files** match the reviewed package; schema 5 remains
current and no migration or production deployment ran. Subsequent CI/documentation
changes do not change this runtime identity.

Source/lock checks, Black, Ruff, the pinned runtime dependency audit, standalone
fixture checks, candidate image build, runtime-byte proof and isolated telemetry/
privacy probes passed. The complete two-fixture matrix passed **1,385 unique
backend cases**, each in its applicable fixture: bank 1,366 passed / 19
fixture-specific skips; Pagila 1,373 passed / 12 fixture-specific skips. The
synthetic dump/restore preserved preference values, schema and revision while
applying the independent session/mail/analysis recovery fences. Private-storage
installation, role/write-denial recovery and the isolated proxy gate passed.
Their containers/volumes were removed with absence confirmed, and pre-existing
running containers were unchanged. No live analytical data, real recipient,
provider exercise or production restore is claimed.

The complete frontend suite passed **399/399**, with no failures or skips. Both
final production builds and manifest/bundle checks passed on frozen source;
the frontend dependency audit reported **zero vulnerabilities**. Initial JS/CSS
delivery is 190,736 gzip bytes for Opal and 190,737 for legacy. The Plotly engine
remains outside the initial graph: 1,211,596 bytes, or 404,237/404,238 gzip bytes
for the respective shell builds. The separate offline cross-language proof
also passed 166 actual account-validator scenarios and matching defaults; it
does not substitute for the canonical API/database tests.

All eight final browser gates passed against the same candidate backend and the
verified final asset set for each shell. Each shell passed **103 synthetic**,
**39 real private-workspace**, **41 Settings** and **37 actual-Plotly** assertions:
220 per shell, 440 total. Each Settings gate measured 128 preset combinations
without contrast failures, exercised both light/dark system media modes, forced
colors and reduced motion, inspected the browser accessibility tree, and reached
all nine categories at 320 CSS pixels with actual control text doubled from 14
to 28 pixels. Save/import/conflict/reset keyboard and focus checks passed in both
shells. Every gate confirmed owned browser/profile/listener/backend cleanup;
no external attempts, live-provider work, runtime errors, console leaks or
protocol failures were observed. These are bounded browser checks, not a full
assistive-technology audit or a claim that every browser zoom combination was
tested. Earlier/intermediate failures remain separate from these final passes.

| Shell | Browser gate | Final status |
| --- | --- | --- |
| Opal | Settings, actual account/device preferences and hostile imports | Passed: 41 assertions; selected screenshots reviewed |
| Opal | Synthetic auth/security/responsive journeys | Passed: 103 assertions |
| Opal | Real private-DB auth/workspace lifecycle | Passed: 39 assertions |
| Opal | Actual Plotly/visual lifecycle with saved Table default | Passed: 37 assertions |
| Legacy | Settings, actual account/device preferences and hostile imports | Passed: 41 assertions; selected screenshots reviewed |
| Legacy | Synthetic auth/security/responsive journeys | Passed: 103 assertions |
| Legacy | Real private-DB auth/workspace lifecycle | Passed: 39 assertions |
| Legacy | Actual Plotly/visual lifecycle with saved Table default | Passed: 37 assertions |

The [portable verification record](evidence/p09/verification.json) retains report/
asset hashes, immutable image identity, measured contrast/reflow/AX summaries,
resource-cleanup results and the remaining release gates. The eight selected
screenshots below use only the fixed synthetic fixture and were visually reviewed.

| Shell | Settings desktop | Light / increased contrast | 320px / doubled text | Actual Plotly |
| --- | --- | --- | --- | --- |
| Opal | [Desktop](evidence/p09/screenshots/opal-settings-desktop.png) | [Light](evidence/p09/screenshots/opal-settings-light-increased.png) | [Mobile](evidence/p09/screenshots/opal-settings-320-double-text.png) | [Chart](evidence/p09/screenshots/opal-desktop-actual-plotly.png) |
| Legacy | [Desktop](evidence/p09/screenshots/legacy-settings-desktop.png) | [Light](evidence/p09/screenshots/legacy-settings-light-increased.png) | [Mobile](evidence/p09/screenshots/legacy-settings-320-double-text.png) | [Chart](evidence/p09/screenshots/legacy-desktop-actual-plotly.png) |

CI now includes the actual P09 Settings gate for each shell and enables the
saved-Table/explicit-chart regression in both P08 visual gates. Artifact retention
adds only bounded synthetic P09 JSON/PNG paths. Changed CI/docs source-policy
checks passed with zero findings. The workflow parsed as YAML, all 20 Bash run
blocks passed syntax checks, and its 24 steps retain the existing action pins,
permissions and concurrency. The required PR and merged-main workflows subsequently passed; see the dated release closeout below.

Native reverse Tab could leave the preference modal despite its native dialog
semantics. The fix explicitly wraps Tab/Shift+Tab across visible enabled controls;
fresh real keyboard checks now prove containment, Escape cancellation and focus
return to the trigger in both shells. Light presets also exposed fixed header,
input and placeholder colors; scoped theme text/muted/surface tokens corrected
them, followed by both 128-preset contrast runs and reviewed light screenshots.
At 320 pixels with doubled text, native search/file inputs and a header flex item
could force horizontal overflow. Bounded shrinking/wrapping of the search and
file-picker grids and header content preserves the native controls; all nine
category reflow checks now pass in each shell.

The earlier route-inventory omission was fixed without changing runtime. Undo
callback/metadata separation, explicit stale-save conflict review and sidebar DOM
ordering have focused regressions and final actual-browser retests. Harness-only
diagnostic/lock-proof problems were corrected separately. Historical failures
and their available metadata remain in the portable evidence; an earlier setup
failure whose cause was not retained is not assigned an invented diagnosis.
All final isolated gates passed at the candidate checkpoint. Required PR/main CI and production verification subsequently passed as recorded below.

Detailed ignored working evidence remains under `.check-results/p09/`; the
sanitized portable record and selected screenshots above are included for review.

Current local records are the canonical package's `summary.json`,
`frontend-verification-final.json`, the final unit/build/bundle logs, and
`browser-opal-settings-20261028T211643365Z/p09-browser-report.json`. These ignored
paths are operator working evidence, not promised files in a fresh Git checkout.

## Rollback

Known cosmetic follow-up from screenshot review: the AQUA wordmark letters are
faint in the legacy shell with the Light preset. The droplet mark, navigation
and functional controls remain visible. This is recorded for human visual
review; it is not a failed ownership, input, resource or functional test.

P09 requires no database migration or irreversible conversion. Roll back backend
and frontend together to the reviewed P08 images/source if required, retaining
schema 5, `app.user_preferences`, existing private database/socket volumes, mail
activation, worker-only provider environment and scheduler. Do not clear saved
preferences to roll back presentation. The older Settings placeholder will not
read the new values; retaining them allows a forward fix to restore customization.

The existing `AQUA_UI_SHELL=opal|legacy` remains a build-time presentation rollback
between the secured shared shells, not a permission or credential switch. P09
preferences operate within either shell. Never roll back to obsolete authentication
or disable private storage to change appearance. A newer schema/client must not
be forced into a version-1 write; keep the record and deploy a compatible reader.

## October 28 release closeout

[PR #52](https://github.com/drewUTSA/Aqua/pull/52) merged with the short title `Phase9 Settings`. Both [PR CI](https://github.com/drewUTSA/Aqua/actions/runs/40773039197) and [main CI](https://github.com/drewUTSA/Aqua/actions/runs/40774686721) passed. Frozen frontend assets were packaged from the exact locally verified P09 builds, proved against both image file sets/nginx configuration, and passed both isolated proxy denial/recovery runs. The source, all 119 installed files, unchanged dependency lock and migrations were compared with the merged commit before cutover.

The controlled web-service deployment passed at 21:58:59 UTC on schema 5 without a migration. Database identity/volumes, environment, password/mail activation, private worker configuration and scheduler were preserved. Exact images are healthy; all origin/public assets matched, with only the pinned pre-existing Cloudflare Analytics HTML insertion. Public private APIs returned 401, readiness remained 404, and the sign-in browser showed enabled password/email fields, registration/recovery links and no initial Plotly load. The browser/profile and disposable image/proxy cleanup were confirmed. No authenticated production account or analytical/provider request was used.

Independent helper review found an evidence-write failure could incorrectly report no production change. The handler now preserves mutation/rollback facts in a fixed stdout fallback; 20 mocked scenarios, 12 public-HTML cases and Linux formatting/correctness gates passed before deployment. The [release record](evidence/p09/release.json) pins images, checks and public hashes. The separately requested homepage simplification will have its own verification and short commit.
