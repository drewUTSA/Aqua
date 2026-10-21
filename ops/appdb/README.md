# Private application storage — P03 operations

P02 is deployed at `5ac90fcca45a6a74bab5d6f792388c05804d87a2`: the private
`aqua_app` database is installed, enabled and verified at schema **1**. That
release still uses legacy Google profile cookies.

This P03 source requires schema **2** and enabled storage for durable
authentication. Its migration/cutover is a separate reviewed release action;
it has not been applied merely by preparing these files.
Use [P03 identity cutover](../../docs/ops/P03_IDENTITY_CUTOVER.md) for the existing
server. **Do not run prepare or bootstrap over that installed database.**
Password login/public registration are later phases.

## Scope and private topology

Run reviewed operator commands as `ben2004`, without sudo, from
`/srv/bank-ai`. These helpers use the existing Docker operator's privileges;
they are project procedures, not a server-access sandbox. They never migrate
the hosted analytical database or change its credentials/connection code.

The dedicated PostgreSQL service has **no TCP listener, published port or
container network**. `aqua_app_data` holds data; `aqua_app_sockets` holds its Unix
socket. The explicitly attached backend/migration jobs mount the socket
read-only at `/run/aqua-app-db` and must also pass SCRAM authentication.
Only postgres inside its DB container has the local peer administrative path.
There is no database route through nginx or Cloudflare.

The owner cannot log in. The migrator may assume that owner for explicit DDL.
Runtime has bounded table DML and cannot alter the schema/version ledger;
backup has SELECT only. Runtime service credentials are not a tenant boundary:
the application derives account ownership from authenticated canonical UUIDs.

Credentials remain under `/home/ben2004/.aqua-runtime/app-storage`, outside the
shared checkout. Directories are 0700; credential/env files are 0600. The single
bootstrap-password mount is 0444 inside that private parent so the unprivileged
PostgreSQL UID can read it. Keep audi's existing project access; never loosen
private paths. Do not print private env files, resolved Compose configuration
or container environment arrays.

Budgets remain 1 GiB RAM, 2 CPUs, 128 PIDs, 32 cluster connections and 24 app-DB
connections, with role caps 12 runtime / 2 migrator / 2 backup. Each backend
process defaults to four pooled connections, eight waiters and a two-second
acquisition deadline. Reconcile aggregate budgets before adding workers.
P03 additionally enforces durable auth budgets and a default five-session cap;
these do not replace P07/P12's wider work/capacity controls.

## Existing P02 server: reviewed P03 migration

Confirm the merged P03 commit and final check evidence, retain previous image
IDs, review a pre-cutover encrypted snapshot and plan an authentication/API
outage. Preserve both volumes, runtime credentials and immutable migration
history. The known untracked `.env.bak` is not an input and must not be read.

The complete sequence and failure handling are in the
[cutover runbook](../../docs/ops/P03_IDENTITY_CUTOVER.md). Its core steps are:

```bash
cd /srv/bank-ai
git status --short
git pull --ff-only origin main
export AQUA_PRIVATE_STORAGE_DIR=/home/ben2004/.aqua-runtime/app-storage
docker compose -f docker-compose.yml -f compose.app-storage.yml build backend frontend
# Verify the reviewed source and exact candidate images before stopping traffic.
docker compose -f docker-compose.yml -f compose.app-storage.yml stop backend
python3 ops/appdb/manage.py migrate --apply-reviewed
# Require status=migrated and schema_version=2 before starting P03.
docker compose -f docker-compose.yml -f compose.app-storage.yml up -d --no-build backend frontend
curl --fail --silent http://127.0.0.1:8000/api/health
curl --fail --silent http://127.0.0.1:8000/api/ready
```

Require healthy services and internal readiness reporting storage ready/schema
**2**. Keep `APP_STORAGE_ENABLED=true` in the existing private runtime file.
Ordinary Compose omits the socket/runtime attachment; use the overlay on every
start/recreate/rebuild sequence. Never make a disabled flag, schema mismatch or
503 appear successful by enabling legacy authentication.

Migration runs only through the reviewed one-off tool. It receives migrator
credentials and the private socket, no analytical/Google/mail environment and
no container network. Checksums, transactional DDL and an advisory lock protect
history and interruption/concurrency. Startup does not migrate. Never edit
`0001_identity.sql` or other applied migrations to repair a failure.

## Fresh installation on an empty host only

This section is for a genuinely new installation, not the current server.
Confirm absence of `aqua-app-db`, `aqua_app_data` and `aqua_app_sockets`, approved
host capacity and the reviewed source/images. Snapshots are not reservations.
An unexpected resource/role stops bootstrap rather than resetting it.

```bash
cd /srv/bank-ai
python3 ops/appdb/manage.py prepare
export AQUA_PRIVATE_STORAGE_DIR=/home/ben2004/.aqua-runtime/app-storage
docker compose -f docker-compose.yml -f compose.app-storage.yml build backend frontend
docker pull postgres@sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826
python3 ops/appdb/manage.py bootstrap --apply-reviewed
python3 ops/appdb/manage.py migrate --apply-reviewed
```

The P03 image applies both versioned migrations and must report schema 2.
Generated runtime settings start with storage disabled. Before attaching P03,
the operator deliberately enables only `APP_STORAGE_ENABLED` in that private
file, preserving the generated DSN and permissions, then uses the overlay
start/readiness checks above. P03 authentication stays unavailable while storage
is disabled.

Preparation is write-once: rerunning it after deliberate runtime activation
refuses the changed default file. Do not overwrite activation or rotate
credentials to force it through. Bootstrap is not repeatable over existing
roles/volumes. Partial failure preserves data/credentials for inspection.
Never run `down -v`, prune volumes, recursively chown data or automatically
reinitialize. Docker images/metadata remain in Docker's normal directories.

Production Python uses the pinned base and hashed dependency graph tested in CI.
Its root context/COPY allowlists exclude secrets and operator credentials.
Dependency changes require refreshed locks and the same release checks.

## Authentication behavior after P03 cutover

All old signed profile cookies are rejected; users sign in again. Sessions and
one-use challenges store token digests. Protected operations check account
status, epoch, expiry and current grant/version; logout commits revocation before
cookie deletion. A failed logout preserves frontend account state and locks the
workspace for an explicit retry. Google configuration is needed for new Google
login, independently of existing-session checks/logout.

Fresh verified Google identities resolve by issuer/subject, never by merging
matching emails. Explicit legacy approvals can seed an absent dataset grant
with provenance; relogin never resurrects a revoked grant. New accounts receive
only owned empty preference defaults, not arbitrary financial-data access.
See [Google/session contract](../../docs/google-signin.md).

## Encrypted off-server collection

The existing Windows Restic foundation and independent recovery-password copy
are operator-confirmed. Do not repeat setup or collect that password. Use the
ordinary Windows account outside Codex's redirected package storage.
The repository is `C:\Users\Benjamin\AppData\Local\Aqua\Backups\repository`.
Let the existing Restic binary request its password privately, or use the
previously reviewed credential helper.

When a real-data collection is reviewed, stream the dump directly to encrypted
Restic storage. `--stdin-from-command` fails the backup if SSH/export fails,
instead of saving truncated pipeline input as a successful snapshot:

```powershell
& 'C:\Users\Benjamin\AppData\Local\Aqua\Backups\bin\restic.exe' -r 'C:\Users\Benjamin\AppData\Local\Aqua\Backups\repository' backup --stdin-from-command --stdin-filename aqua-app.pgdump --tag aqua-app -- 'C:\Windows\System32\OpenSSH\ssh.exe' -F NUL -T -i 'C:\Users\Benjamin\.ssh\aqua-work-20261016\id_ed25519' -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ForwardAgent=no -o ClearAllForwardings=yes -o PermitLocalCommand=no ben2004@192.168.1.200 '/usr/bin/python3 -E -s -B /srv/bank-ai/ops/appdb/export.py'
```

Require exit code zero, record snapshot ID/source/schema/time and run
`restic check --read-data`. Export is backup-role-only, preserves table ACLs and
has an initial 120-second / 512-MiB budget. Review capacity when it fails; do not
remove caps. Account records, password hashes and session digests must remain
encrypted, never sent to chat/terminal capture.

Synthetic checks do not establish a real snapshot, schedule, retention policy,
production restore or measured RPO/RTO. Initial planning targets remain daily
collection, 24-hour RPO and four-hour RTO, subject to a real restore measurement
and this PC being available. Before public launch, agree targets, monitor missed
backups and preserve recovery access independent of the PC/site.
Do not prune existing snapshots as part of this phase.

## Non-destructive recovery drill

Use a trusted snapshot matching the reviewed software/schema. Verify the
encrypted repository, restore its dump into an owner-only operator folder and
transfer it privately to
`/home/ben2004/.aqua-runtime/app-storage/recovery/aqua-app.pgdump`.
Check owner, mode 0600, no links, size budget and snapshot selection without
printing data.

These commands create a **new** `aqua_app_restore` database in the dedicated
cluster. They fail if it exists, never overwrite `aqua_app` and never contact
the hosted analytical DB. Do not attach the drill database to public traffic.

```bash
cd /srv/bank-ai
docker exec aqua-app-db psql -X -v ON_ERROR_STOP=1 -U postgres -d postgres -c 'CREATE DATABASE aqua_app_restore OWNER aqua_app_owner TEMPLATE template0'
docker exec aqua-app-db psql -X -v ON_ERROR_STOP=1 -U postgres -d postgres -c 'REVOKE ALL ON DATABASE aqua_app_restore FROM PUBLIC'
docker exec -i aqua-app-db pg_restore --exit-on-error --no-owner --role=aqua_app_owner -U postgres -d aqua_app_restore < /home/ben2004/.aqua-runtime/app-storage/recovery/aqua-app.pgdump
docker exec -i aqua-app-db psql -X -v ON_ERROR_STOP=1 -U postgres -d aqua_app_restore < ops/appdb/restore_session_fence.sql
docker exec aqua-app-db psql -X -v ON_ERROR_STOP=1 -U postgres -d aqua_app_restore -c "SELECT max(version) FROM app.schema_migrations; SELECT has_table_privilege('aqua_app_runtime','app.users','INSERT'),has_table_privilege('aqua_app_runtime','app.schema_migrations','UPDATE'); SELECT count(*) FROM app.sessions WHERE revoked_at IS NULL;"
```

For a P03 snapshot require latest schema **2**, privileges true/false, zero
unrevoked sessions, matching record counts and account ownership invariants.
The fence increments account epochs and consumes outstanding challenges before
any recovered instance can reopen. P03 authentication checks those stored fields.
Reconcile post-snapshot grant revocations/deletions before restoring access;
session fencing alone cannot recover changes absent from an older backup.

Historical P02 snapshots contain schema 1; they are not ready for P03 code.
Any schema upgrade or production recovery from such a snapshot needs its own
reviewed recovery procedure, not the fixed live-database migration command
pointed at an arbitrary restore target. Preserve the original database and
encrypted snapshot until recovery is independently verified.

## Rollback and isolated verification

A failed migration transaction leaves no partial schema. After schema 2 commits,
the P02 image (which expects schema 1) is not a compatible rollback target.
Use maintenance/forward repair as the cutover runbook describes. Once durable
sessions are issued, only use releases that retain their revocation/epoch/grant
checks. Never restore the old signed-cookie path or drop account data to undo
code changes. Preserve both volumes and private credentials.

CI covers both fixture datasets, immutable/interrupted/concurrent migrations,
effective role separation, bounded pool/admission abuse, copied challenge/session
replay, epoch/grant revocation and recovery. Synthetic dump/restore checks preserve
rows/ACLs and fence restored sessions. The installer rehearsal uses random names,
fake credentials, socket-only SCRAM and exact owned-resource cleanup.
Run trusted code on isolated runners; do not execute untrusted PR code with
Docker privileges on the production server.

Reference: [Restic command-stream backups](https://restic.readthedocs.io/en/stable/040_backup.html#reading-data-from-stdin).
