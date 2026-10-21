# Aqua
Ask a database a question in plain English. Get back the data, a readable summary, and the exact SQL that produced it.

Current checkpoint: [P03 durable identity and sessions](docs/implementation/P03.md), prepared for human review on `codex/p03-identity-sessions`. [P02 PR #38](https://github.com/drewUTSA/Aqua/pull/38) is merged at `5ac90fc` and deployed with private application storage enabled at schema 1; see [the release record](docs/implementation/P02_RELEASE.md). The [approved phased specification](docs/planning/AQUA_CODEX_HANDOFF.md) covers the remaining frontend/backend work. Verification: [check runner guide](tools/checks/README.md).

## Private application storage and identity

The application PostgreSQL service is separate from the hosted analytical database. It has no network, TCP listener or published port. Only explicitly attached backend/migration jobs receive the Unix socket, with separate runtime, owner, migrator and backup privileges. Public nginx refuses `/api/ready`; `/api/health` stays independent of the databases and model.

P03 code requires enabled storage and schema 2 for authentication. It adds canonical account IDs, opaque digest-only sessions, single-use Google challenges, durable revocation, current grants, atomic session caps and bounded shared login admission. The frontend preserves a locked workspace when logout is not confirmed. Password login, persistent chats, Plotly and full Settings remain later phases.

Do not bootstrap over the installed DB or launch new code before its explicit migration. Follow the [P03 cutover procedure](docs/ops/P03_IDENTITY_CUTOVER.md) after review/merge. Every legacy signed cookie will require reauthentication. Rollback must preserve durable revocation; there is no stateless fallback. The [storage operator guide](ops/appdb/README.md) covers installation, encrypted collection and separate-database recovery. Keep production signup and private dataset grants under their own launch review.
