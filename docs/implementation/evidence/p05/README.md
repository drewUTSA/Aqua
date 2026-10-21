# P05 review evidence

`artifact-hashes.json` binds the sanitized files in this directory. Browser
screenshots contain synthetic accounts only; no provider credentials, cookies,
proof values, request bodies or real application data are recorded.

- `frontend-unit.xml`: 117 Node unit/contract tests.
- `browser-report.json`: 56 Chrome checks against the extracted frontend image.
- `real-browser-report.json`: 16 actual FastAPI/private PostgreSQL browser checks,
  including real-time admission cooldown, with fake Google and captured email.
- `frontend-image.json` and `local-checks.json`: undeployed image identity, exact
  asset hashes, production-flag rebuild equality and protected source hashes.
- `quality-checks.json`: formatting, lint, 12 fixture lifecycle regressions and
  independent source review. Remote CI is pending human push.
- `real-browser-*-failure.json`: retained failed whole runs. The first exhausted
  the legitimate challenge budget; its weak error assertion was corrected to
  distinguish 429 from 401. A portable fixture-image default then needed the
  local wrapper's explicit image ID. The final cleanup failure was Docker 29's
  alternative exact-name absence wording; `cleanup-inventory.json` confirms no
  resources remained. The corrected full run passed without waiving cleanup.

The combined test uses a fixed synthetic HTTPS mail origin and an exact loopback
browser origin; it does not exercise public HTTPS, live Google or mail delivery.
Two explicit fixture admission-window steps separate independent scenarios.
The rate-limit recovery scenario waits for the actual server cooldown without
those steps or automatic credential retries. No analytical database, AI model,
production signup or mail worker is used. See `../../P05.md` and the separate
P04 release evidence for application/server enforcement and rollout boundaries.
