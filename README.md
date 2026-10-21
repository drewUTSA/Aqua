# Aqua
Ask a database a question in plain English. Get back data, a readable summary and the exact SQL that produced it.

Latest review update: P05 is committed in PR #42. Its first CI run stopped at
the browser fixture's startup; the [tested fixture correction](docs/implementation/P05_CI_FIX.md)
awaits a human follow-up commit/push. This supersedes the pre-commit checkpoint
below. Production remains P04; wait for all PR checks before merging P05.

Current checkpoint: [P04 PR #41](https://github.com/drewUTSA/Aqua/pull/41) is deployed at `067fb5a`, with private storage ready at schema 3 and all new password/mail flags disabled; see [the release record](docs/implementation/P04_RELEASE.md). [P05 Opal shell and account browser journeys](docs/implementation/P05.md) passed the [handoff follow-up](docs/implementation/P05_ROLLBACK.md) for reversible presentation, legal-navigation draft preservation, bounded title search and viewport/delivery evidence: 120 unit cases, plus 77 synthetic and 20 actual-backend browser checks for each shell. Copy/hash guards verify the actual checkout; human commit/push, remote PR checks and merge remain required. P05 is not deployed. The [approved phased specification](docs/planning/AQUA_CODEX_HANDOFF.md) covers the remaining frontend/backend work. Verification: [check runner guide](tools/checks/README.md).

## Private application storage and identity

The application PostgreSQL is separate from the hosted analytical database. It has no network, TCP listener or published port. Backend/migration jobs attach only the private Unix socket, with distinct runtime, owner, migrator and backup privileges. nginx refuses public readiness; liveness stays independent of databases/models. P03's canonical UUID accounts, opaque digest-only sessions, one-use Google challenges, durable revocation, grants and session caps are deployed. Legacy signed cookies require fresh authentication.

P04 source requires explicit schema 3. Its backend adds email-first registration, fresh-password verification, password login, reset/session fencing, bounded Argon2id work, an offline common-password corpus and encrypted account mail with reserved recovery/security capacity. All password/signup/recovery/mail flags default off. P05 supplies the user-facing password forms and approved Opal shell; full activation also requires a reviewed worker/delivery journey. Owned chats, Plotly and Settings remain later phases.

Frontend presentation is selected at build time: `AQUA_UI_SHELL=opal` (default) or
`legacy` for Docker/Compose, and `VITE_AQUA_UI_SHELL` for direct Vite builds.
Legacy restores classic blue/glass presentation using the same current auth,
account ownership and semantic composer. It is not a security-policy or user
preference switch. Invalid values fail; rebuild only the frontend to change it.
See [the rollback procedure](docs/implementation/P05_ROLLBACK.md).

Follow the [P04 migration/activation procedure](docs/ops/P04_PASSWORD_CUTOVER.md) after review/merge and the [mail worker runbook](docs/ops/P04_ACCOUNT_MAIL.md) before sending messages. Never bootstrap the installed DB or start new code before its explicit migration. Rollback must preserve durable revocation, grants and data; use a compatible forward fix or maintenance. The [storage guide](ops/appdb/README.md) covers encrypted collection and separate-database recovery. General signup never grants private analytical access.
