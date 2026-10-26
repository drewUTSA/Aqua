# Aqua
Ask a database a question in plain English. Get back data, a readable summary and the exact SQL that produced it.

Current checkpoint (October 26, 2026): P05 issue closure is complete at code
checkpoint `8a5c71d`, including [repair PR #43](https://github.com/drewUTSA/Aqua/pull/43).
Required PR and merged-main checks passed. The Opal frontend and patched P04
backend are healthy; private storage remains at schema 3 with all
password/registration/recovery/mail/worker activation flags disabled.

P06 is ready to start and has not started. See the
[final repair and deployment record](docs/implementation/P05_CI_CLOSURE.md)
and [earlier release evidence](docs/implementation/P05_RELEASE_READINESS.md).
The [approved phased specification](docs/planning/AQUA_CODEX_HANDOFF.md)
covers the remaining work. Verification: [check runner guide](tools/checks/README.md).

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
