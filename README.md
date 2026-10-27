# Aqua
Ask a database a question in plain English. Get back data, a readable summary and the exact SQL that produced it.

Current checkpoint (October 26, 2026): P05 production activation and P06 are
complete and live at code `6872e41`, private schema 4. Password login,
registration, recovery and encrypted AQUA-branded mail are active; delivery
runs in its separate bounded scheduled worker. Chats, messages, recents,
projects and personal prompts persist in the private application database.
Required PR/main checks and controlled production verification passed. See
[activation evidence](docs/implementation/P05_PRODUCTION_ACTIVATION.md) and
[P06 evidence](docs/implementation/P06_PERSISTENT_WORKSPACE.md).

P07 is now authorized and in progress, with no P07 deployment yet. It adds
durable bounded analysis, follow-up context, progress and server cancellation;
see [the P07 record](docs/implementation/P07_DURABLE_ANALYSIS.md). Plotly and
complete Settings follow in P08/P09. The [approved phased specification](AQUA_CODEX_HANDOFF.md)
governs the order. Verification: [check runner guide](tools/checks/README.md).

## Private application storage and identity

The application PostgreSQL is separate from the hosted analytical database. It has no network, TCP listener or published port. Backend/migration jobs attach only the private Unix socket, with distinct runtime, owner, migrator and backup privileges. nginx refuses public readiness; liveness stays independent of databases/models. P03's canonical UUID accounts, opaque digest-only sessions, one-use Google challenges, durable revocation, grants and session caps are deployed. Legacy signed cookies require fresh authentication.

P04 introduced email-first registration, fresh-password verification, password login, reset/session fencing, bounded Argon2id work, an offline common-password corpus and encrypted account mail with reserved recovery/security capacity. Activation flags remain off by default for new installations; this production installation completed the reviewed P05 activation. P06 requires schema 4; the P07 candidate requires the separately reviewed schema-5 migration before it can start.

Frontend presentation is selected at build time: `AQUA_UI_SHELL=opal` (default) or
`legacy` for Docker/Compose, and `VITE_AQUA_UI_SHELL` for direct Vite builds.
Legacy restores classic blue/glass presentation using the same current auth,
account ownership and semantic composer. It is not a security-policy or user
preference switch. Invalid values fail; rebuild only the frontend to change it.
See [the rollback procedure](docs/implementation/P05_ROLLBACK.md).

Follow the [P04 migration/activation procedure](docs/ops/P04_PASSWORD_CUTOVER.md) after review/merge and the [mail worker runbook](docs/ops/P04_ACCOUNT_MAIL.md) before sending messages. Never bootstrap the installed DB or start new code before its explicit migration. Rollback must preserve durable revocation, grants and data; use a compatible forward fix or maintenance. The [storage guide](ops/appdb/README.md) covers encrypted collection and separate-database recovery. General signup never grants private analytical access.
