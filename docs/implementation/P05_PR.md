# P05 PR draft — Opal workspace and secure account journeys

Status: all final run-3 local follow-up gates passed after the last contrast
correction; evidence is sealed. Copy/hash guards verify the actual checkout
before human review.
The human owns commit, push, PR creation and
merge. Remote CI must pass after push; local reports do not imply a remote result.

## Proposed title

P05: add reversible Opal workspace and secure dual-login journeys

## Proposed description

AQUA now uses the approved charcoal/Opal shell with subtle static specks, a
responsive sidebar and a full-width chat entry. The composer, model choice,
suggestions and visit-local recents stay usable. The account menu opens Settings
or signs out; Settings/back preserves the conversation and draft. Full saved
history, customizable Settings and the conditional Plotly pane remain P06–P09.

The operator can rebuild with `AQUA_UI_SHELL=legacy` to restore the classic
blue/glass layout without downgrading authentication. Both presentations share
the semantic composer, account owner, mobile dialog and secure auth routes.
The flag is build-time only, accepts `opal|legacy`, and defaults to Opal.
Visit-local title search is bounded and makes no network request.

The new account screens connect to Google's supported control and the existing
P04 password API independently. Registration first proves mailbox ownership;
verification/reset never sign in automatically. The client obtains a fresh
action challenge before one POST, honors Retry-After, shows fixed safe errors
and requires deliberate retries. Passwords and link proofs are not persisted;
link fragments are removed before UI/provider setup.

Canonical account state, confirmed revocation and metadata-only cross-tab
invalidation protect private UI. A failed logout retains the draft behind an
inert privacy lock. Reset locks both at request start and completion, including
a lost response and another tab's interim session revalidation. An account may
use Settings without receiving analytical data permission. Legal navigation and
Back preserve the existing account owner and locked draft during pending/failed
logout; a direct policy-page visit remains public without auth bootstrap.

### Verification

- 120 Node unit/contract cases and both production builds passed. Invalid shell
  values are rejected; environment canaries are excluded and demo flags stay off.
- Each exact image passed 77 synthetic Chrome checks for two-tab isolation,
  auth states, hostile output/redirects, cooldown/no-replay behavior, local search,
  Settings/legal/Back preservation and responsive/forced-color behavior.
- Each shell passed 20 combined Chrome/FastAPI/schema-3 PostgreSQL checks for
  actual permission denial, reset/session revocation, forged CSRF and natural
  429 recovery with no automatic retry. Browser/listener/profile and backend
  resources were removed and absence confirmed. Google/email are fake/captured;
  no actual provider or hosted-data requests were made.
- Both explicit production rebuilds byte-match their tested image assets. Image
  digests and sealed reports are in `P05_ROLLBACK.md` and `evidence/p05/rollback/`.
- 12 test-fixture cleanup regressions, Black (145 Python files), Ruff, source/lock
  and 16 protected-file hash checks passed.
- Desktop/tablet/mobile/intermediate/320px, shortened keyboard height and 200%
  landing/active conversation text checks passed. Representative screenshots were
  reviewed. These checks are not a complete accessibility certification.
- Delivery is measured: initial JS 440,078/440,080 bytes and CSS 48,503 bytes; the
  chart chunk stays deferred at login. Legacy workspace alone requests the retained
  2,111,901-byte logo. Local loopback timing is recorded without a production SLO claim.
- P04's unchanged backend/gateway have separate release evidence: 1,056 distinct
  backend cases across two dataset fixtures and 98 proxy abuse/recovery requests.
  See `P04_RELEASE.md` for counts, skips and limits.
- Both browser gates are added to CI for the shell variants. Remote GitHub CI is
  **pending human push**.

Findings and paired regressions are retained in `P05.md`,
`P05_ACTION_BOUNDARIES.md`, `P05_ROLLBACK.md` and `evidence/p05/`. No required
failure is waived; the later handoff audit's rollback/navigation gaps are fixed
and their new regressions passed. The final checkout hash guard remains required.

### Deployment and rollback

P04 PR #41 is already healthy at main `067fb5a` and schema 3. This change adds no
migration, backend permission expansion or runtime dependency. All five new
password/mail flags remain OFF; no worker, provider secret or public signup is
activated. Hosted analytical data/configuration and applied migrations are
unchanged. Both P05 candidate images are built but not deployed.

After merge, retain the schema-3 backend and private-storage overlay and deploy
the reviewed frontend with a bounded smoke check. Select the maintained `legacy`
presentation for a frontend-only visual rollback, preserving the same current
password/Google routes and security controls. An authentication regression needs
a compatible forward fix or maintenance state. Never restore the P03/schema-2 backend on
the schema-3 database. Provider delivery, production capacity and broader launch
penetration testing remain explicit later gates.
