# Isolated UI reliability journeys

Run against a reviewed production build with both demo flags false. Every run
retains P05's existing 240-second/900-request/320-API ceilings, synthetic APIs,
external-request denial, console/bearer checks and exact browser/profile/server
cleanup. Each command starts a fresh page/profile; default and `c-notices`
journeys retain their original checks. No backend, live provider or production
origin is used by these P05 modes.

From `frontend/`, set `AQUA_P05_DIST` to the absolute frozen build directory,
`AQUA_P05_ARTIFACT_DIR` to a new dedicated evidence directory, the expected shell
with `AQUA_P05_EXPECTED_SHELL=opal` or `legacy`, and `AQUA_CHROME_EXECUTABLE` to
the local Chrome executable. Run one of these exact closed modes, using a
separate evidence directory for each:

```text
node --input-type=module -e "await import('./checks/p05-browser.mjs?journey=optional-settings')"
node --input-type=module -e "await import('./checks/p05-browser.mjs?journey=optional-prompts')"
node --input-type=module -e "await import('./checks/p05-browser.mjs?journey=projects-initial-failure')"
node --input-type=module -e "await import('./checks/p05-browser.mjs?journey=prompts-initial-failure')"
node --input-type=module -e "await import('./checks/p05-browser.mjs?journey=settings-search')"
node --input-type=module -e "await import('./checks/p05-browser.mjs?journey=composer-layout')"
node --input-type=module -e "await import('./checks/p05-browser.mjs?journey=public-routes')"
```

Only fixed optional chunk GETs or the selected fixed collection GET can receive
a synthetic 503. Mutation routes are never intercepted as failures or retried.
List modes restore the same fixture route, require no automatic retry, then use
the explicit UI retry. Optional failures must retain the same composer, draft
and mounted account. Healthy Settings mode also verifies the modified shortcut
and records hint/disclaimer bounding rectangles, font/line sizes, overlap and
gap at 1440×980 and 390×844 before and after its Settings round trip. Geometry is observed without changing CSS or
silently treating an overlap as fixed. Review the phase-labeled screenshots and
`report.json`'s `reliability_journey.composer_footer_geometry`.

`composer-layout` records the same geometry on a fresh chart-free entry without
expecting the new search or shortcut behavior. It can therefore run against the
original and changed frozen builds for comparison. Font loading and finite
composer animations must settle within the original deadline; raw gap/overlap
is retained for review, without a CSS fix or automatic visual-approval claim.

`public-routes` covers every one of the fourteen `LOCAL_PATHS` at 1440×980 and
320×844, using only existing synthetic session responses for authenticated
workspace/Settings. It submits no form or other mutation. It checks visible
headings/content, reflow, keyboard navigation, inert account-mail routes and a
scrolled SPA policy switch. It saves 28 full-document PNGs (bounded to 1441×12000
CSS pixels and the unchanged 12MiB encoded screenshot ceiling). Internal
Settings scroll regions are covered separately by the nine-category P09
journey. The loopback SPA server is not nginx HTTP404/TLS evidence.

## Separate real-fixture table reset

On the existing trusted Linux Docker fixture host, use the same production
build and immutable runtime image as the original P08 journey. Do not point its
bridge at a server/remote Docker context or private application configuration.
From `frontend/`, the exact environment and command are:

```sh
export AQUA_P05_EXPECTED_SHELL=opal
export AQUA_P08_DIST=/absolute/frozen/opal/dist
export AQUA_P08_ARTIFACT_DIR=/absolute/new/evidence/table-reset
export AQUA_CHROME_EXECUTABLE=/absolute/local/google-chrome
export AQUA_P08_BRIDGE_EXECUTABLE=/absolute/local/python
export AQUA_P08_BRIDGE_ARGS_JSON='["-u","../tools/checks/p08_browser_backend.py","--image","sha256:REVIEWED_EXISTING_RUNTIME_IMAGE_ID"]'
node checks/p08-table-reset-browser.mjs
```

Replace only the clearly marked paths and immutable image ID with the reviewed
local values; the bridge retains its fixed source, roles, dataset, operation and
resource limits. Repeat with a separately frozen Legacy build and evidence
directory. This entry uses **two** existing `P08 chart oversized` fake jobs in a
fresh fixture, exercises page/sort/precision, then verifies reset on the new
result and explicit selection of the earlier result. It never appends work to
the full twelve-job P08 suite or increases that cap. The full candidate CSP is
enforced in this fixture; no production policy or real Google acceptance is
claimed. Require a passed `p08-table-reset-report.json`, zero real provider
calls, and confirmed exact-resource cleanup before accepting the result.
