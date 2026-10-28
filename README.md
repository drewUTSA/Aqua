# Aqua
Ask a database a question in plain English. Get back data, a readable summary and the exact SQL that produced it.

Current checkpoint: P00 through P08 are complete and live at code checkpoint
`d76be9a` (PR #50), private schema 5. Analysis retains P07's durable requests,
owned progress, server cancellation and exact numeric values. Requested visuals
now open a bounded lazy Plotly pane with linked table/chart controls, compatible
zoom, keyboard resizing and mobile navigation.

Password login, registration, recovery and encrypted AQUA-branded mail remain
active. P08 required no migration; the private database/socket volumes,
scheduled worker and existing data were preserved. Required PR/main checks and
controlled production health/asset verification passed. See
[P08 release evidence](docs/implementation/P08_PLOTLY_VISUALS.md),
[P07 durable analysis](docs/implementation/P07_DURABLE_ANALYSIS.md) and
[activation](docs/implementation/P05_PRODUCTION_ACTIVATION.md).

P09 Settings is implemented and locally verified in the October 28 review
candidate: 1,385 backend cases, 399 frontend tests and all eight browser gates
passed. The authorized Git/CI release workflow and PR/main CI remain pending. See
[P09 Settings and preferences](docs/implementation/P09_SETTINGS_PREFERENCES.md).
P10 through P13 have not started.
The [approved phased specification](AQUA_CODEX_HANDOFF.md) governs the order.
Verification: [check runner guide](tools/checks/README.md).

## Private application storage and identity

The application PostgreSQL is separate from the hosted analytical database. It has no network, TCP listener or published port. Backend/migration jobs attach only the private Unix socket, with distinct runtime, owner, migrator and backup privileges. nginx refuses public readiness; liveness stays independent of databases/models. P03's canonical UUID accounts, opaque digest-only sessions, one-use Google challenges, durable revocation, grants and session caps are deployed. Legacy signed cookies require fresh authentication.

P04 introduced email-first registration, fresh-password verification, password login, reset/session fencing, bounded Argon2id work, an offline common-password corpus and encrypted account mail with reserved recovery/security capacity. Activation flags remain off by default for new installations; this production installation completed the reviewed P05 activation. P06 requires schema 4; the deployed P08 release retains schema 5. New installations must apply the reviewed migrations explicitly before starting the matching backend.

Frontend presentation is selected at build time: `AQUA_UI_SHELL=opal` (default) or
`legacy` for Docker/Compose, and `VITE_AQUA_UI_SHELL` for direct Vite builds.
Legacy restores classic blue/glass presentation using the same current auth,
account ownership and semantic composer. It is not a security-policy or user
preference switch. Invalid values fail; rebuild only the frontend to change it.
See [the rollback procedure](docs/implementation/P05_ROLLBACK.md).

Follow the [P04 migration/activation procedure](docs/ops/P04_PASSWORD_CUTOVER.md) after review/merge and the [mail worker runbook](docs/ops/P04_ACCOUNT_MAIL.md) before sending messages. Never bootstrap the installed DB or start new code before its explicit migration. Rollback must preserve durable revocation, grants and data; use a compatible forward fix or maintenance. The [storage guide](ops/appdb/README.md) covers encrypted collection and separate-database recovery. General signup never grants private analytical access.
