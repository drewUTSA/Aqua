# P04 password migration and activation procedure

**Reviewed procedure for a later approved cutover; not executed by writing this file.** P03 is live at `c25a3332e67f644e94c6ab3b6e80155dacf7c56b`, private schema 2. P04 requires schema 3. Password signup/recovery, actual email integration and the worker remain disabled until the prerequisites below pass. The hosted analytical database is outside this procedure.

## Preconditions and disabled deployment

1. Merge the reviewed P04 PR only after the complete final candidate matrix, actual-image packaging/installer/restore, adversarial replay/takeover/enumeration/resource/fairness checks, nginx limiter recovery and source/dependency gates pass. Record commit, image IDs, source/lock/corpus hashes and cleanup evidence. A source test or a green proxy check alone does not satisfy this gate.
2. Confirm healthy P03 services, schema-2 readiness, Unix-socket storage, current private files and existing Google/session settings. Do not display environment files, keys, hashes, tokens, cookies or private account data. Preserve the known `.env.bak` without reading it. Keep both database volumes; do not rerun `prepare`/`bootstrap`, remove volumes or alter analytical credentials.
3. Collect and integrity-check a fresh encrypted off-server snapshot before the schema-3 change using the existing [backup procedure](../../ops/appdb/README.md#encrypted-off-server-collection). P03's `62737bad...` snapshot is historical schema 1, not a replacement for this current snapshot. Verify the independent recovery copy remains usable without sending a secret to chat. Collection is not a production restore; a separate recovery rehearsal is required by the release plan.
4. Preserve the previous image IDs and plan a short API/authentication outage. Keep `PASSWORD_AUTH_ENABLED=false`, `PASSWORD_REGISTRATION_ENABLED=false`, `PASSWORD_RECOVERY_ENABLED=false`, `ACCOUNT_MAIL_ENABLED=false` and `ACCOUNT_MAIL_WORKER_ENABLED=false` for this deployment. Existing Google and durable-session behavior must remain testable after migration.

As `ben2004`, from the reviewed `/srv/bank-ai` checkout, synchronize only the approved merge and build/verify both release images. Existing Docker/private-folder permissions suffice; this is not permission to change unrelated server services.

```bash
cd /srv/bank-ai
git status --short
git pull --ff-only origin main
export AQUA_PRIVATE_STORAGE_DIR=/home/ben2004/.aqua-runtime/app-storage
docker compose -f docker-compose.yml -f compose.app-storage.yml build backend frontend
```

Confirm the images contain the exact tested source, hashed runtime lock and all three corpus assets: digest file, provenance JSON and MIT license. The digest file must retain LF bytes, length 708,370 and SHA-256 `a5b8b74b66c0ed54d90098285cb0dbe02217ae41d7c91f0c57cf4a761e14521a`. Run the current packaged-source/lock guard and the image's corpus validation; do not fix an integrity failure by loosening validation or editing the expected hash. Stop on unexpected source/image drift.

```bash
docker compose -f docker-compose.yml -f compose.app-storage.yml stop backend
python3 ops/appdb/manage.py migrate --apply-reviewed
docker compose -f docker-compose.yml -f compose.app-storage.yml up -d --no-build backend frontend
```

Require the migration's fixed successful report with **schema_version 3** before starting the new backend. Migration is explicit, checksum checked and transactional; web startup never runs DDL. Require healthy services and internal readiness reporting private storage ready/schema 3, continued runtime DDL/ledger denial with subsequent read recovery, socket-only/no-TCP isolation and no new public readiness exposure. Repeat only the approved bounded public smoke. Aggressive replay/flood/hash exercises remain in isolated fixtures; no production mailbox or authentication flood is authorized here.

Verify existing Google bootstrap, unauthenticated `/me` rejection, legacy-cookie rejection and session revocation behavior. A separately scoped real operator sign-in may check canonical identity and logout without publishing cookies/tokens. The new password capabilities/endpoints must truthfully report disabled/unavailable. Do not treat a private DB port, disabled storage or stateless fallback as an availability fix.

## Activation prerequisites

Deployment with disabled flags is distinct from enabling the user journey. Before enabling password registration or recovery:

- Complete P05's approved login/signup/verification/reset forms and two-user browser journeys. Implement password-manager/autofill/paste support, correct action-bound bootstrap/Origin/CSRF, no-store behavior and account-scoped state cleanup. `/verify-email#token=...` and `/reset-password#token=...` must consume the fragment into private memory, clear it promptly, prevent referrer/analytics leakage and never log or reflect the bearer value. The P04 backend alone does not provide those finished forms.
- Install a separately generated 32-byte outbox encryption key into reviewed owner-only secret files for web encryption and worker decryption. It must differ from session/database/provider secrets and be recoverable independently. Keep the Resend Sending-access key restricted to `account.aqua-ai.us` in the separate worker-only mail environment. Do not mount the application's full environment or business DB/model/Google secrets into the mail worker. Do not print existing secrets or create a new provider key automatically.
- Verify sender/domain readiness and applicable account limits without spending quota or reading credentials. Obtain separate explicit authorization for any real delivery smoke; the earlier setup-email approval is not standing permission to send more messages. Verify actual inbox delivery and verification/reset completion without sharing the token.
- Review and install an explicit worker schedule and monitoring, with one-job invocations (`python -m auth.mailworker`) no more frequently than the documented budget. There is no API background thread or automatic scheduler. Review delivery/queue purpose reservations, lease/retry/expiry bounds, outage behavior and aggregate alerts in the [mail runbook](P04_ACCOUNT_MAIL.md). Log only fixed event categories/counts, never mailbox addresses, links or secrets.
- Demonstrate new-account no-dataset access, Google-only reset rejection, same-email conflict safety, epoch/session invalidation, failed-delivery recovery and meaningful rate/resource controls with separate fixture users. Public launch still requires the applicable P12/P13 gates and an explicit audience/release decision.

Enable flags deliberately and independently after those checks. `PASSWORD_AUTH_ENABLED` enables the method; registration and new recovery requests have their own flags. Pausing issuance must not unnecessarily lock out existing sessions/password logins or invalidate already issued proofs. `ACCOUNT_MAIL_ENABLED` and `ACCOUNT_MAIL_WORKER_ENABLED` govern their separate integration. Record each change, configuration hash without values, limited smoke result and rollback contact. Do not broaden Google approvals or business-data grants while opening general authentication.

## Failure handling and recovery

**Hash slots:** the global maximum is two active request hashes. Slots do not expire because a paused process may still be consuming Argon2 memory. If a crash or DB-release failure leaves retired slots, disable new password attempts and stop **every process capable of hashing against this app DB**, including all replicas and one-off jobs. Confirm no such worker can resume. Inspect count/age metadata only, then have the operator clear only proven retired `app.password_hash_slots` rows under the reviewed private DB role and transaction. Restart the reviewed bounded worker configuration and test legitimate recovery. Never clear slots on a timer, while another worker is running, or as an automatic response to 429; that can oversubscribe memory.

**Mail:** disable the explicit worker to contain sends and independently pause new issuance if needed. Keep pending jobs/key for reviewed recovery; do not extend expired tokens, reset attempt counters or replay unknown acceptance with a new UUID/idempotency key. Successful/permanent/invalid/exhausted/expired jobs wipe encrypted bearer ciphertext; consumed challenges delete linked jobs. Delivery acceptance is not proof of inbox delivery. An outage does not authorize secret dumps or unbounded retries.

**Schema/code:** a failed migration rolls back transactionally; investigate the fixed diagnostic and exact candidate before retrying. After schema 3 commits, a P03 image expecting schema 2 is not a compatible rollback. Keep the new flags disabled and use a reviewed schema-compatible forward fix or maintenance state. Do not edit applied migrations/checksums, accept legacy cookies, disable durable storage or rewind authorization to regain availability.

**Restore:** restore only to a separate private recovery DB with all attached auth/mail workers stopped. Apply the reviewed [restore fence](../../ops/appdb/restore_session_fence.sql) before reconnecting any application: advance account epochs, revoke restored sessions, consume outstanding challenges, clear slots belonging only to detached retired workers, cancel/wipe restored pending mail and release its restored delivery lease. Preserve already spent delivery quotas rather than giving a restored database a fresh sending allowance. Verify grants/tombstones, ledger/corpus versions, privileges and absence of active old proofs/jobs. The recovery fence is not a live cleanup script and must never run against a working production database as routine maintenance. A separately approved recovery cutover follows its own evidence/release decision.

Retain migration history, private credentials, both database volumes, encrypted snapshots and aggregate evidence. Report actual checks and remaining failures. No procedure here implies a completed production restore, public password launch, provider delivery guarantee or unrestricted production penetration test.

The pre-merge email/content follow-up is part of the reviewed schema-3 candidate: verify recipient rolling history, pending-job coalescing and exact challenge/template binding along with the earlier tests. Preserve `app.mail_recipient_budget` when applying the restore fence; resetting it would grant fresh unwanted-mail allowances. The table is application data, not a routine cleanup target. This source still does not enable actual sending; consult [P04_SECURITY_REVIEW.md](../implementation/P04_SECURITY_REVIEW.md).
