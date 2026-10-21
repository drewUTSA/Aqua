# Add private application storage with bounded connections and transactional migrations

AQUA needs durable account/session storage separate from the hosted analytical
dataset. Add the private PostgreSQL schema, separate owner/migrator/runtime/backup
roles, explicit checksum-ledger migrations, bounded pooled transactions and safe
internal readiness. The opt-in deployment uses a shared Unix socket, no database
TCP listener or network, private credentials and resource limits. Existing Google
authentication and analytical connection code remain unchanged.

Use the same pinned Python base and hashed runtime dependencies for production
and CI, preventing the dependency drift detected during P01's release. Add
reviewable install/export/restore procedures and synthetic recovery fencing.

Validation:

- All 761 distinct backend tests pass across isolated bank/Pagila fixtures.
- Actual installer/Compose rehearsal passes with socket-only password auth,
  repeat migrations, denied DDL, restricted binary export and exact cleanup.
- Synthetic restore preserves rows/ACLs and invalidates stored sessions/challenges.
- The 35-request proxy exercise proves rate-limit containment/recovery and denies
  public readiness probes without backend work.
- Exact-image source verification (38 files), dependency consistency/advisory
  checks, source guard, Black and Ruff pass. See `docs/implementation/P02.md`.

Migration/deployment requires human review. Ordinary Compose leaves storage off;
follow `ops/appdb/README.md` before installing the separate DB or attaching its
socket. No persistent DB, real-data export or public signup was activated by this
change. Roll back code/config while preserving data and credentials. P03 supplies
actual account/session authorization and caps; P04 supplies password login and
P07 supplies shared operation/global admission. Real recovery targets, scheduling
and capacity measurements remain later release gates.
