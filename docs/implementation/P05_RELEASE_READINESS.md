# P05 release readiness — October 26, 2026

Latest issue-closure follow-up: see [P05_CI_CLOSURE.md](P05_CI_CLOSURE.md) for the
reviewed transport/cleanup repair, current regression counts and publication
gate. The results below retain the earlier direct-access verification evidence.

P05 PR #42 is merged into `main` at
`5d1bc1f5fad4712df3b625966944fcc966ea2ff0`, including the earlier CI fixture fix.
Older notes saying the PR is open or that fix is uncommitted are historical.

The user authorized running isolated tests/security checks and updating the
current merged application after passing checks. After initial password-only
access failed, the user installed a dedicated public key and direct SSH/Docker
access was verified. The Windows SSH alias `aqua-codex` uses that key.
No application deployment was performed: P05 was already live and healthy.

## Direct server verification and fresh isolated checks

The checkout at `/srv/bank-ai` is `5d1bc1f`; its existing untracked `.env.bak`
was left unread and unchanged. Before and after testing, these live images and
healthy service states were unchanged:

- Frontend: `aqua-p05-release:opal-5d1bc1f`, image
  `sha256:78eba557e860481c32194b44380336f491d05a790cc9c66af3482232c4ed6997`.
- Backend: image
  `sha256:b253e68f307957d232819991057416910d86e407173dde876c3dee193602bedb`.
- Private database: healthy; internal readiness reports schema 3. All five
  password/registration/recovery/mail/worker flags are false or unset.

Fresh checks used trusted committed source and disposable synthetic containers,
with the existing resource, traffic and cleanup bounds:

| Gate | Result |
| --- | --- |
| Backend against actual deployed runtime image | All 1,056 distinct cases passed across bank/Pagila fixtures |
| Synthetic dump/restore and security fences | Passed; rows/privileges/recipient budget preserved |
| Disposable private database installer | Passed; repeat migration, SCRAM, DDL denial/recovery, memory-only export, no network/TCP |
| Isolated nginx attack/defense/recovery exercise | Passed; 98 requests, 42 admitted operations, bypass/denial and cooldown checks |
| Real FastAPI/schema-3 browser suites via SSH fixture transport | Opal 20/20 and classic 20/20 passed, including natural rate-limit recovery |
| Source/lock guards | Passed |
| Fixture cleanup/startup regressions | 12/12 and 7/7 passed |
| Pinned PostgreSQL temporary-server readiness regression | Passed; old readiness race reproduced and final-process gate verified |

All created test containers/volumes were removed with absence confirmed. Final
service inventory contained only the original application/database/Open WebUI
services. No production provider, mail or analytical-data work was exercised.
The existing Starlette/httpx test-client deprecation warning remains.

The first backend packaging attempt correctly rejected symlinks in the server's
untracked `backend/.venv`. A clean `git archive HEAD` snapshot avoided that local
runtime directory without weakening the source guard. The failed run remains
recorded. An initial browser bridge invocation exceeded its argument-count guard;
it failed before provisioning. The corrected SSH invocation stayed within the
existing bound; neither fixture protocol guard was changed.

Server reports and the clean source snapshot are under
`/srv/bank-ai/.check-results/direct-20261026-QTveMz/`. Selected synthetic reports
were copied to local `.check-results/p05-current/server/`. Real browser reports
are in local `real-opal-ssh/report.json` and `real-legacy-ssh/report.json` under
`.check-results/p05-current/`.

## Checks performed in this session

- Restored frontend dependencies with `npm ci --ignore-scripts --no-fund`.
  The install audit reported zero vulnerabilities. Vite is the locked 7.3.7.
- All 133 frontend unit/contract tests passed with the locked dependencies.
- Opal and classic production builds passed with demo/mock mode disabled.
- Opal's synthetic browser gate passed all 77 checks before the test change
  and all 77 after it. Classic's first run stopped after 29 passing checks;
  after the test change it passed all 77.
- Both final browser reports confirm bounded synthetic traffic, no external
  request attempts, and browser/profile/listener cleanup. These are frontend
  attack/prevention/recovery checks, not live penetration tests.
- JavaScript syntax validation and `git diff --check` passed for the test change.

Reports are local, ignored artifacts under `.check-results/p05-current/`:
`unit.log`, `opal/report.json`, `legacy/report.json`,
`legacy-retest/report.json`, and `opal-retest/report.json`.
The original classic failure remains available rather than being overwritten.

## Test change prepared for review

`frontend/checks/p05-browser.mjs` now waits for an editable, visible field before
filling it. Waiting only for the route shell could race the protected form's
loading state and produce `page_evaluation_failed`. The bounded wait preserves
the existing assertion and does not bypass disabled controls or alter app code.
This test-only change is uncommitted and is not deployed.

That field wait is now included in the broader CI repair described in
`P05_CI_CLOSURE.md`. No migration or production configuration change is involved.

## Public delivery verification

Three bounded read-only HTTPS requests checked the homepage and its JavaScript
and stylesheet. The homepage returned HTTP 200 and Cloudflare `DYNAMIC`.
Both assets returned 200 and matched the freshly built Opal files byte-for-byte:

| Public asset | SHA-256 |
| --- | --- |
| `/assets/index-BtVueq-Z.js` | `d0385487cfb264dad7909abe886b357a17162a638b7b19e2f0f89678836c97c7` |
| `/assets/index-BfmamgzU.css` | `b15b71f2e3c990bb99d24122dda4eb2151ad1982e798b4925a501f85d490c853` |

This confirms public delivery of the P05 frontend. Separate direct checks above
establish server checkout/container/schema/flag state. Live provider callbacks,
account login, email delivery and global Cloudflare cache state were not tested.

## Remaining gates and access

- PR-head [run 39696566307](https://github.com/drewUTSA/Aqua/actions/runs/39696566307)
  passed historically. Merged-main
  [run 39697212411](https://github.com/drewUTSA/Aqua/actions/runs/39697212411)
  failed with `browser_protocol_deadline` and zero synthetic browser assertions.
  Its backend, disposable database installer, proxy security, frontend unit,
  audit and build steps passed; real-backend and classic browser steps skipped.
  The cause of this separate protocol timeout is unresolved.
- A requested rerun returned GitHub API 403, `Resource not accessible by
  integration`. Actions write permission or a human rerun is needed.
- Docker/WSL and an accessible Python runtime remain unavailable locally;
  the fresh remote isolated checks above now cover the previously unrun backend,
  installer, proxy and actual-database browser suites. These do not turn the
  historical failed GitHub run green or establish its timeout's cause.
- Direct key-based SSH and Docker access now work without password entry.
- Before any later replacement, inspect actual server state and pass required
  gates. P05's reviewed procedure builds and recreates only the frontend with
  `compose.app-storage.yml` retained. Preserve the private database and backend;
  a full Compose shutdown is unnecessary for this frontend update.

No application container/database/Cloudflare configuration, password/mail
activation, Git commit/push, or PR was changed. The user added SSH authorization;
a dedicated alias was saved in the local Windows SSH configuration. Required
unrun/failed checks remain gates; this report is not a full release approval.
