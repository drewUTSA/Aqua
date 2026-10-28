# Aqua
Ask a database a question in plain English. Get back data, a readable summary and the exact SQL that produced it.

Current checkpoint: P00 through P09 are complete and live at
`7c0caae` (PR #53, `Phase9 Homepage`), private schema 5. The home page uses
Projects/Recents, conditional New Chat, one bottom account menu and one composer
model chooser. Answers share the page canvas and the composer compacts after
the first question. Durable requests, cancellation, exact values, optional
Plotly visuals and all nine Settings categories remain available.

Both required CI runs and controlled frontend-only production verification
passed. Database volumes, backend, authentication, encrypted branded mail and
the scheduled worker were preserved. See [homepage evidence](docs/implementation/P09_HOMEPAGE_SIMPLIFICATION.md)
and [Settings](docs/implementation/P09_SETTINGS_PREFERENCES.md).

P10a account foundation passed 1,440 backend cases, 455 frontend tests, both
builds and ten browser gates (568 checks). Profile edits and read-only sign-in
method/session reviews save separately from preferences. The candidate awaits
required CI and a verified private schema-6 release. P10b is separate; P10
remains incomplete and P11–P13 have not started.
The [approved phased specification](AQUA_CODEX_HANDOFF.md) governs the order.
Verification: [check runner guide](tools/checks/README.md).

## Private application storage and identity

The application PostgreSQL is separate from the hosted analytical database. It has no network, TCP listener or published port. Backend/migration jobs attach only the private Unix socket, with distinct runtime, owner, migrator and backup privileges. nginx refuses public readiness; liveness stays independent of databases/models. P03's canonical UUID accounts, opaque digest-only sessions, one-use Google challenges, durable revocation, grants and session caps are deployed. Legacy signed cookies require fresh authentication.

P04 introduced email-first registration, fresh-password verification, password login, reset/session fencing, bounded Argon2id work, an offline common-password corpus and encrypted account mail with reserved recovery/security capacity. Activation flags remain off by default for new installations; this production installation completed the reviewed P05 activation. P06 requires schema 4; the deployed P09 release retains schema 5. New installations must apply the reviewed migrations explicitly before starting the matching backend.

Frontend presentation is selected at build time: `AQUA_UI_SHELL=opal` (default) or
`legacy` for Docker/Compose, and `VITE_AQUA_UI_SHELL` for direct Vite builds.
Legacy restores classic blue/glass presentation using the same current auth,
account ownership and semantic composer. It is not a security-policy or user
preference switch. Invalid values fail; rebuild only the frontend to change it.
See [the rollback procedure](docs/implementation/P05_ROLLBACK.md).

Follow the [P04 migration/activation procedure](docs/ops/P04_PASSWORD_CUTOVER.md) after review/merge and the [mail worker runbook](docs/ops/P04_ACCOUNT_MAIL.md) before sending messages. Never bootstrap the installed DB or start new code before its explicit migration. Rollback must preserve durable revocation, grants and data; use a compatible forward fix or maintenance. The [storage guide](ops/appdb/README.md) covers encrypted collection and separate-database recovery. General signup never grants private analytical access.
