# Aqua
Ask a database a question in plain English. Get back data, a readable summary and the exact SQL that produced it.

Current checkpoint (October 26, 2026 local time): P00 through P07 are complete and live
at code `1d08364` (PR #48), private schema 5. Analysis requests persist through
reloads, use bounded server execution and follow-up context, and expose owned
progress and server cancellation. Workspace results include honest provenance
and exact numeric values where ordinary JavaScript numbers would lose precision.

Password login, registration, recovery and encrypted AQUA-branded mail remain
active. The separate scheduled worker, private database/socket volumes and
existing data were preserved. Required PR/main checks, encrypted backup,
migration and controlled production verification passed. See
[P07 release evidence](docs/implementation/P07_DURABLE_ANALYSIS.md),
[P06 workspace](docs/implementation/P06_PERSISTENT_WORKSPACE.md) and
[activation](docs/implementation/P05_PRODUCTION_ACTIVATION.md).

P08 Plotly and conditional visuals are next; P08 onward has not started. The
[approved phased specification](AQUA_CODEX_HANDOFF.md) governs the order.
Verification: [check runner guide](tools/checks/README.md).

## Private application storage and identity

The application PostgreSQL is separate from the hosted analytical database. It has no network, TCP listener or published port. Backend/migration jobs attach only the private Unix socket, with distinct runtime, owner, migrator and backup privileges. nginx refuses public readiness; liveness stays independent of databases/models. P03's canonical UUID accounts, opaque digest-only sessions, one-use Google challenges, durable revocation, grants and session caps are deployed. Legacy signed cookies require fresh authentication.

P04 introduced email-first registration, fresh-password verification, password login, reset/session fencing, bounded Argon2id work, an offline common-password corpus and encrypted account mail with reserved recovery/security capacity. Activation flags remain off by default for new installations; this production installation completed the reviewed P05 activation. P06 requires schema 4; the deployed P07 release requires schema 5. New installations must apply the reviewed migrations explicitly before starting the matching backend.

Frontend presentation is selected at build time: `AQUA_UI_SHELL=opal` (default) or
`legacy` for Docker/Compose, and `VITE_AQUA_UI_SHELL` for direct Vite builds.
Legacy restores classic blue/glass presentation using the same current auth,
account ownership and semantic composer. It is not a security-policy or user
preference switch. Invalid values fail; rebuild only the frontend to change it.
See [the rollback procedure](docs/implementation/P05_ROLLBACK.md).

Follow the [P04 migration/activation procedure](docs/ops/P04_PASSWORD_CUTOVER.md) after review/merge and the [mail worker runbook](docs/ops/P04_ACCOUNT_MAIL.md) before sending messages. Never bootstrap the installed DB or start new code before its explicit migration. Rollback must preserve durable revocation, grants and data; use a compatible forward fix or maintenance. The [storage guide](ops/appdb/README.md) covers encrypted collection and separate-database recovery. General signup never grants private analytical access.
