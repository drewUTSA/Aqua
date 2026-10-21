# Private application storage — P02 operator procedure

P02 prepares the persistence foundation. Accounts still use the existing Google
cookie flow until P03's reviewed identity/session cutover. No password login,
public registration, customer data grant, or session-count limit is enabled here.
The application database is separate from the hosted analytical database.

## Review and scope

Apply this procedure only after reviewing/merging P02. Run as `ben2004`, without
sudo, from `/srv/bank-ai`. Docker access already carries host privileges; these
helpers are project-specific procedures, not a sandbox for untrusted operators.
Read the scripts before running them. The installer never repairs or resets
existing database roles/volumes; an unexpected existing resource stops it.

The dedicated database has **no TCP listener, published port or container network**.
`aqua_app_data` holds PostgreSQL data; `aqua_app_sockets` holds only its Unix socket.
Only the DB and explicitly attached backend/migrator receive these volumes.
The backend mounts the socket read-only at `/run/aqua-app-db`; SCRAM passwords
are required in addition to filesystem access. `postgres` is peer-only inside
the DB container. There is no database path through nginx or Cloudflare.

The owner cannot log in. The migrator can assume the owner for explicit DDL;
the runtime has bounded table DML and cannot write the version ledger; backup
has SELECT only. Runtime row ownership must be enforced by P03 and later
repositories: these service credentials themselves are not a tenant boundary.

Credentials are generated at `/home/ben2004/.aqua-runtime/app-storage`, outside
the shared checkout. The directory is 0700; credential/env files are 0600.
Only the bootstrap password mount is 0444 inside that private parent, so the
unprivileged PostgreSQL container can read its single mounted file. Preserve
`audi`'s existing project write access; never loosen private-directory permissions.
Do not print these files, place them in Git, or attach their contents to a report.

## Fresh installation after human migration review

First confirm the reviewed source, Docker/Compose availability, disk space,
and absence of `aqua-app-db`, `aqua_app_data`, `aqua_app_sockets`. Name snapshots
are not reservations. Image and volume metadata use Docker's normal directories.
The dedicated DB budget is 1 GiB RAM, 2 CPUs, 128 PIDs, 32 server connections,
24 application-DB connections, with role caps 12 runtime / 2 migrator / 2 backup.
Each web worker defaults to a four-connection pool and eight waiting callers.
Do not multiply worker counts without reconciling these budgets.

```bash
cd /srv/bank-ai
git pull --ff-only origin main
docker compose build backend frontend
docker pull postgres@sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826
python3 ops/appdb/manage.py prepare
python3 ops/appdb/manage.py bootstrap --apply-reviewed
python3 ops/appdb/manage.py migrate --apply-reviewed
```

Bootstrap is deliberately not repeatable over existing roles or volumes. A failed
attempt preserves data and private credentials; inspect its exact resources before
any recovery. Do not run `down -v`, prune volumes, recursively chown data, change
another account's access, or automatically reinitialize. The versioned migration
is repeatable and transactional; changed checksums or unknown history stop it.
Web startup never runs migrations. Keep bootstrap/migrator credentials out of
the web container, and never supply analytical, Google or email secrets to it.

The production Dockerfile uses the same pinned, hashed dependency graph as CI.
The root build context allows only runtime Python, migrations and lock files.
Dependency upgrades must refresh the lock and pass the same release checks.

## Attachment and activation

The generated `runtime.env` starts with `APP_STORAGE_ENABLED=false`. Storage is
opt-in; ordinary Compose does not create the private DB or attach its socket.
After the installation is reviewed, use the overlay when deploying the backend:

```bash
export AQUA_PRIVATE_STORAGE_DIR=/home/ben2004/.aqua-runtime/app-storage
docker compose -f docker-compose.yml -f compose.app-storage.yml up -d backend frontend
curl --fail --silent http://127.0.0.1:8000/api/health
curl --fail --silent http://127.0.0.1:8000/api/ready
```

With the flag false, readiness truthfully reports storage disabled. Enabling it
requires changing only that flag in the private runtime file, recreating the
backend with the overlay, and confirming readiness reports schema version 1.
Do this as part of the reviewed activation/cutover, not as an implicit side effect
of preparing credentials. Existing Google authentication is unchanged by P02.
Public nginx denies `/api/ready` and normalized variants; use the loopback backend
port for operator diagnostics. `/api/health` stays independent of DB/model outages.

## Encrypted off-server collection

The existing Windows Restic foundation and independent recovery-password copy
are operator-confirmed. P02 does not repeat their setup or collect that password.
Use the ordinary Windows account outside Codex's redirected package storage.
The repository is `C:\Users\Benjamin\AppData\Local\Aqua\Backups\repository`.
Run its existing Restic binary in a private console; let Restic request its
password interactively, or use the previously reviewed private credential helper.

After the DB installation and real-data export are reviewed, this PowerShell
command streams the dump directly into encrypted Restic storage, without a
plaintext dump file. `--stdin-from-command` cancels the backup on SSH/export
failure, unlike a pipeline that might save truncated input as a successful backup:

```powershell
& 'C:\Users\Benjamin\AppData\Local\Aqua\Backups\bin\restic.exe' -r 'C:\Users\Benjamin\AppData\Local\Aqua\Backups\repository' backup --stdin-from-command --stdin-filename aqua-app.pgdump --tag aqua-app -- 'C:\Windows\System32\OpenSSH\ssh.exe' -F NUL -T -i 'C:\Users\Benjamin\.ssh\aqua-work-20261016\id_ed25519' -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ForwardAgent=no -o ClearAllForwardings=yes -o PermitLocalCommand=no ben2004@192.168.1.200 '/usr/bin/python3 -E -s -B /srv/bank-ai/ops/appdb/export.py'
```

Require exit code zero. Record the snapshot ID, source/schema version and time;
then run `restic check --read-data` against that repository. The export has a
120-second / 512-MiB initial budget, uses only the backup role and preserves table
ACLs. A budget failure stops collection; review capacity instead of removing caps.
Do not run the export directly into chat/terminal capture. The output contains
account data, password hashes and session digests and must remain encrypted.

No real database snapshot, schedule, retention pruning or measured production
RPO/RTO is claimed by P02's synthetic checks. Suggested initial planning targets
are daily collection, 24-hour RPO and four-hour RTO, subject to an actual restore
measurement and PC availability. Before launch, agree targets, monitor missed
backups, preserve independent recovery access, and address loss of the entire site.
Do not prune any existing snapshots during this phase.

## Non-destructive recovery drill

Use a trusted snapshot matching the reviewed schema/software version. Verify the
encrypted repository before restoring its dump into an owner-only operator folder,
then transfer it over SSH/SFTP to a private recovery folder under
`/home/ben2004/.aqua-runtime/app-storage`. Treat the restored dump as a secret.
Never pass it through Codex output. Confirm file ownership, mode 0600, no links,
size budget, and the selected snapshot ID before running the commands below.

These commands create **a new database**, `aqua_app_restore`, in the dedicated
app cluster. They fail if it already exists, never overwrite `aqua_app`, and never
contact the hosted company DB. Leave public traffic connected only to `aqua_app`.
The file name below is fixed for a separately reviewed transferred dump.

```bash
cd /srv/bank-ai
docker exec aqua-app-db psql -X -v ON_ERROR_STOP=1 -U postgres -d postgres -c 'CREATE DATABASE aqua_app_restore OWNER aqua_app_owner TEMPLATE template0'
docker exec aqua-app-db psql -X -v ON_ERROR_STOP=1 -U postgres -d postgres -c 'REVOKE ALL ON DATABASE aqua_app_restore FROM PUBLIC'
docker exec -i aqua-app-db pg_restore --exit-on-error --no-owner --role=aqua_app_owner -U postgres -d aqua_app_restore < /home/ben2004/.aqua-runtime/app-storage/recovery/aqua-app.pgdump
docker exec -i aqua-app-db psql -X -v ON_ERROR_STOP=1 -U postgres -d aqua_app_restore < ops/appdb/restore_session_fence.sql
docker exec aqua-app-db psql -X -v ON_ERROR_STOP=1 -U postgres -d aqua_app_restore -c "SELECT version FROM app.schema_migrations; SELECT has_table_privilege('aqua_app_runtime','app.users','INSERT'),has_table_privilege('aqua_app_runtime','app.schema_migrations','UPDATE'); SELECT count(*) FROM app.sessions WHERE revoked_at IS NULL;"
```

Require schema 1, privileges `true/false`, zero unrevoked sessions, preserved
record counts and expected application invariants. `restore_session_fence.sql`
increments account epochs and consumes outstanding challenges before a recovered
DB may be attached. P03 must check these fields on every authenticated operation;
the P02 drill proves their stored fencing, not acceptance/rejection by future auth.
Do not attach the drill DB to the web app or reuse it for production automatically.
A production recovery/cutover needs its own reviewed host, credentials, traffic
isolation, current app image, validation and rollback plan. Preserve the original
DB and encrypted backup until recovery is independently verified.

## Rollback and isolated verification

Before P03, disable application storage/remove the socket overlay and restore the
previous reviewed application images if needed. Preserve both DB volumes and all
private credentials. Never reverse a migration by dropping data. A migration
failure rolls its schema transaction back; bootstrap failures retain their new
volume for inspection. After P03, rollback must also preserve durable session
revocation; never re-enable the legacy cookie path as an auth fallback.

CI runs both fixture datasets, transactional interruption/concurrency checks,
role separation, bounded pool/queue abuse and recovery, and a synthetic dump/restore
with privilege and epoch checks. `tools/checks/storage_deployment.py` additionally
exercises this installer with random resource names, synthetic credentials,
no network/host ports, real SCRAM authentication and cleanup by resource ownership.
All Docker checks require trusted source on an isolated runner; do not run
untrusted PR code with Docker access on the production host.

Reference: [Restic streaming command backups](https://restic.readthedocs.io/en/stable/040_backup.html#reading-data-from-stdin).
