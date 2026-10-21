# Aqua
Ask a database a question in plain English. Get back the data, a readable summary, and the exact SQL that produced it.

Implementation checkpoint: [P02](docs/implementation/P02.md) (private storage prepared; migration and PR review pending). P01 PR #37 is merged and deployed at `07055eb`. P00 was merged in [PR #36](https://github.com/drewUTSA/Aqua/pull/36). Approved phased specification: [AQUA handoff](docs/planning/AQUA_CODEX_HANDOFF.md). Verification: [check runner guide](tools/checks/README.md).


## Private application storage (P02)

The reviewed [operator guide](ops/appdb/README.md) describes the separate, opt-in
PostgreSQL service, runtime/owner/migrator/backup roles, versioned migrations,
bounded connections and encrypted backup/recovery procedure. The DB has no TCP
listener or network; the backend attaches a read-only Unix socket volume only
when its explicit Compose overlay is used. Existing Google authentication and
hosted analytical DB connections remain unchanged. `/api/ready` is an internal
operator diagnostic; public nginx refuses it. `/api/health` remains DB-free.

Do not activate the persistent DB, run real-data exports or enable public signup
merely by checking out this branch. P02 stops for human migration/PR review;
P03 supplies the actual durable user/session/grant behavior.
