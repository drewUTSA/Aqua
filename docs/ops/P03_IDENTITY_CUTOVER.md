# P03 identity cutover and recovery

**Reviewed operator procedure; not yet executed.** P02 is currently deployed at
`5ac90fcca45a6a74bab5d6f792388c05804d87a2`, with `aqua_app` schema 1 and storage
enabled. This procedure deliberately replaces its legacy profile-cookie auth.
All existing users must sign in again. The hosted analytical DB is not migrated.

## Preconditions

1. Merge the reviewed P03 PR only after its final backend, browser, migration,
   abuse/recovery and proxy checks pass. Record the merged commit and exact
   candidate image IDs in the release record.
2. Confirm healthy P02 services, schema 1, the existing socket attachment,
   `APP_STORAGE_ENABLED=true`, and the private runtime folder. Check names and
   permissions without printing environment files or secrets. Keep existing
   Google configuration, Origin and session secret; no new server-wide grant is
   required. A session-secret rotation is a separate deliberate reauthentication
   event, not routine setup.
3. Review collection of a pre-cutover encrypted DB snapshot using the existing
   [app-storage backup procedure](../../ops/appdb/README.md#encrypted-off-server-collection).
   Record its successful snapshot/check result; do not infer a real backup or
   restore from a synthetic test. Use the already confirmed independent recovery
   password copy without sending it to chat.
4. Plan a short authentication/API outage while migration and both images are
   replaced. Retain the old images and both DB volumes for diagnosis, but do not
   plan to restore unrevocable cookie acceptance after cutover.

## Migrate before starting new code

Run as `ben2004` from the reviewed `/srv/bank-ai` checkout, without sudo. Do not
run `prepare`/`bootstrap` over the installed database. Do not run `down -v`, remove
volumes, reset roles or modify hosted analytical credentials.

```bash
cd /srv/bank-ai
git status --short
git pull --ff-only origin main
export AQUA_PRIVATE_STORAGE_DIR=/home/ben2004/.aqua-runtime/app-storage
docker compose -f docker-compose.yml -f compose.app-storage.yml build backend frontend
```

Verify that `main` is the reviewed P03 merge and that the images correspond to the
tested source/lock before continuing. Stop if unexpected tracked edits, image
drift or service changes appear; the known `.env.bak` is not input to this
procedure and must not be read or committed. Preserve the previous image IDs
without dumping container environment/configuration values.

```bash
docker compose -f docker-compose.yml -f compose.app-storage.yml stop backend
python3 ops/appdb/manage.py migrate --apply-reviewed
```

Require `status=migrated` and `schema_version=2`. The one-off migration uses only
the dedicated migrator credentials and shared socket, with no container network.
It checks immutable ledger checksums and applies `0002_identity_policy.sql`
transactionally. It does not call Google or a model, and startup never runs it.
An interrupted or failed migration must not be treated as success; preserve its
state and investigate the fixed diagnostic before another attempt.

```bash
docker compose -f docker-compose.yml -f compose.app-storage.yml up -d --no-build backend frontend
curl --fail --silent http://127.0.0.1:8000/api/health
curl --fail --silent http://127.0.0.1:8000/api/ready
```

Require healthy containers, dependency-free liveness and internal readiness with
storage ready/schema **2**. A disabled storage flag or schema mismatch is a
failure, not a reason to fall back to legacy authentication. Record image IDs,
source commit and non-secret health output.

## Acceptance checks

Repeat the bounded public smoke checks on both hosts: `/api/health` succeeds,
`/api/ready` stays private, oversized input is rejected and private API responses
are not cached. Keep aggressive replay/rate/concurrency tests in isolated
fixtures; use their final P03 evidence as the release prerequisite. No production
provider flood or customer query is part of this smoke check.

For a separately scoped operator-controlled sign-in check, verify fresh Google
login, a canonical UUID profile, the correct approved/no-dataset state and
server-confirmed logout. Never paste credentials, cookies or CSRF tokens into
chat or logs. Existing signed cookies must receive 401 and require a new login.
A failed Google callback consumes its challenge; restart with fresh
`/api/auth/config` and nonce rather than reusing the failed attempt. Google
configuration failure must not prevent an existing valid durable session from
being checked or logged out.

Record the release checks honestly. Synthetic copied-cookie, epoch, revocation,
grant-revocation and restore tests establish their scoped behaviors; they are not
evidence of a successful real off-server restore or unrestricted production
penetration test. Keep P03 at its cutover checkpoint until required checks pass.

## Failure handling and rollback

- **Before migration commits:** keep backend stopped while diagnosing. A failed
  transaction leaves no partial schema. Retry only after confirming the failure
  cause and reviewed image; never edit an applied migration or its checksum.
- **After schema 2 but before successful P03 acceptance:** keep traffic in an
  unavailable/maintenance state and use a reviewed forward fix. P02 readiness
  expects schema 1, so its image is not a compatible schema-2 rollback target.
- **After durable sessions are issued:** rollback only to a reviewed release that
  continues checking durable revocation, epoch and grants. Do not add a stateless
  cookie fallback or disable storage to make authentication appear healthy.
- **Data recovery:** restore to a separate private recovery database first using
  the reviewed app-storage procedure, fence restored sessions/challenges and
  verify schema/privileges before any separate production recovery cutover.
  Do not replace the live database or rewind authorization from an old snapshot
  as an automatic code rollback.

Preserve data/socket volumes, private credentials, encrypted snapshots and
migration history throughout. P04 recovery/password endpoints and P10 session
management are later implementations; do not advertise them as available during
this rollout.
