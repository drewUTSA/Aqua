-- Apply ONLY to a recovered app database before reconnecting the application.
-- Recovered cookies and outstanding recovery links must not regain validity.
BEGIN;
SET LOCAL ROLE aqua_app_owner;
UPDATE app.users SET auth_epoch = auth_epoch + 1;
UPDATE app.sessions SET revoked_at = now() WHERE revoked_at IS NULL;
UPDATE app.auth_challenges SET consumed_at = now() WHERE consumed_at IS NULL;
-- Only a separate recovered DB with no attached workers reaches this fence.
-- Retired hash workers cannot release slots. Bearer mail cannot replay;
-- schema-7 token-free notice obligations are fenced separately below.
DELETE FROM app.password_hash_slots;
UPDATE app.account_mail_control SET lease_id=NULL,lease_expires_at=NULL WHERE singleton;
-- Older backups remain restorable. Recovery never resumes an analysis or
-- repeats a model call. Saved completed conversation results stay intact.
DO $$
BEGIN
 IF to_regclass('app.account_security_requests') IS NOT NULL THEN
  UPDATE app.account_security_requests SET consumed_at=now() WHERE consumed_at IS NULL;
  -- Bearers cannot revive. Mandatory token-free notices retain their stable
  -- UUID/body/attempt history and provider idempotency window; they are not
  -- optional consent and are independent of the now-consumed requests.
  UPDATE app.account_mail SET state='expired',ciphertext=decode(repeat('00',30),'hex'),
   lease_id=NULL,lease_expires_at=NULL WHERE state IN ('pending','sending')
   AND purpose NOT IN ('password_changed','password_added','email_changed','google_linked','google_unlinked');
  UPDATE app.account_mail SET
   state=CASE WHEN expires_at<=now() THEN 'expired'
    WHEN attempts>=3 OR first_attempt_at<=now()-interval '23 hours' THEN 'failed' ELSE 'pending' END,
   ciphertext=CASE WHEN expires_at<=now() OR attempts>=3 OR first_attempt_at<=now()-interval '23 hours'
    THEN decode(repeat('00',30),'hex') ELSE ciphertext END,
   lease_id=NULL,lease_expires_at=NULL WHERE state IN ('pending','sending')
   AND purpose IN ('password_changed','password_added','email_changed','google_linked','google_unlinked');
 ELSE
  -- Older schema backups retain their reviewed historical fence behavior.
  UPDATE app.account_mail SET state='expired',ciphertext=decode(repeat('00',30),'hex'),
   lease_id=NULL,lease_expires_at=NULL WHERE state IN ('pending','sending');
 END IF;
 IF to_regclass('app.account_action_proofs') IS NOT NULL THEN
  UPDATE app.account_action_proofs SET consumed_at=now() WHERE consumed_at IS NULL;
 END IF;
 IF to_regclass('app.analysis_requests') IS NOT NULL THEN
  UPDATE app.workspace_totals SET content_bytes=GREATEST(0,content_bytes-
   (SELECT COALESCE(sum(reserved_bytes),0) FROM app.analysis_requests WHERE state IN ('pending','queued','running','cancelling'))) WHERE singleton;
  UPDATE app.workspace_usage u SET content_bytes=GREATEST(0,u.content_bytes-r.bytes)
   FROM (SELECT user_id,sum(reserved_bytes) AS bytes FROM app.analysis_requests
         WHERE state IN ('pending','queued','running','cancelling') GROUP BY user_id) r WHERE u.user_id=r.user_id;
  UPDATE app.messages SET status='interrupted' WHERE status='pending';
  UPDATE app.analysis_requests SET state='interrupted',reserved_bytes=0,finished_at=now()
   WHERE state IN ('pending','queued','running','cancelling');
 END IF;
 IF to_regclass('app.analysis_jobs') IS NOT NULL THEN
  -- Job context/legacy response bytes are separate from result reservations.
  UPDATE app.workspace_totals SET content_bytes=GREATEST(0,content_bytes-
   (SELECT COALESCE(sum(content_bytes),0) FROM app.analysis_jobs)) WHERE singleton;
  UPDATE app.workspace_usage u SET content_bytes=GREATEST(0,u.content_bytes-r.bytes)
   FROM (SELECT user_id,sum(content_bytes) AS bytes FROM app.analysis_jobs
         GROUP BY user_id) r WHERE u.user_id=r.user_id;
  UPDATE app.analysis_jobs SET state='interrupted',stage='interrupted',
   version=version+1,lease_token=lease_token+1,finished_at=now()
   WHERE state IN ('queued','running','cancelling');
  UPDATE app.analysis_jobs SET question='',context='[]',response=NULL,
   content_bytes=0,session_digest=decode(repeat('00',32),'hex'),
   lease_owner=NULL,lease_until=NULL,physical_until=NULL;
  -- This is safe only after old web processes/children have been stopped.
  DELETE FROM app.analysis_streams;
  -- Pre-recovery progress must not replay as a current running operation.
  DELETE FROM app.analysis_events;
  -- Preserve spent admission budgets; recovery must not mint fresh model work.
 END IF;
END;
$$;
COMMIT;
