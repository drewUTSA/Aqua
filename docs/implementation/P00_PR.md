# Establish isolated AQUA checks and fix dependency advisories

Backend tests previously inherited DATABASE_URL and `.env`, which could direct
permission/DDL probes at a shared database. This change confines integration
tests to disposable synthetic bank/Pagila databases, blocks accidental service
calls, and records cleanup and coverage across both fixtures. It also captures
the current API contracts and adds CI for tests, build, formatting, lint,
dependency advisories and high-confidence secret patterns.

The audit found outdated certifi and Vite packages. Raise certifi's minimum to
2026.10.19 and pin Vite 7.3.7; the final package audits report no known findings.
The Linux check runtime is hash-locked. Mechanical Black changes have unchanged
production Python syntax trees. Connection modules and hosted database code are
unchanged. No runtime service or persistent database was modified.

Validation: 675 distinct backend tests pass across both fixtures; all 47 frontend
tests and the Vite build pass; Ruff, Black equivalence/check, direct lock range
validation and pip check pass. Disposable containers/source are removed. The
existing large frontend bundle warning and TestClient deprecation remain visible.
GitHub execution awaits this PR; production/OAuth/email/load tests are deferred
to their specified implementation phases.

See [P00 evidence, boundaries and rollback](P00.md). This PR completes the
baseline preparation checkpoint, not the frontend/backend redesign or release.
