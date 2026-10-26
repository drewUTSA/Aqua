-- Apply ONLY to a recovered app database before reconnecting the application.
-- Recovered cookies and outstanding recovery links must not regain validity.
BEGIN;
SET LOCAL ROLE aqua_app_owner;
UPDATE app.users SET auth_epoch = auth_epoch + 1;
UPDATE app.sessions SET revoked_at = now() WHERE revoked_at IS NULL;
UPDATE app.auth_challenges SET consumed_at = now() WHERE consumed_at IS NULL;
-- Only a separate recovered DB with no attached workers reaches this fence.
-- Retired hash workers cannot release slots; restored mail must not replay.
DELETE FROM app.password_hash_slots;
UPDATE app.account_mail SET state='expired',ciphertext=decode(repeat('00',30),'hex'),
 lease_id=NULL,lease_expires_at=NULL WHERE state IN ('pending','sending');
UPDATE app.account_mail_control SET lease_id=NULL,lease_expires_at=NULL WHERE singleton;
-- Schema-3 backups remain restorable. P06 never resumes a web request from a
-- restored pending row or makes a second provider call automatically.
DO $$
BEGIN
 IF to_regclass('app.analysis_requests') IS NOT NULL THEN
  UPDATE app.workspace_totals SET content_bytes=GREATEST(0,content_bytes-
   (SELECT COALESCE(sum(reserved_bytes),0) FROM app.analysis_requests WHERE state='pending')) WHERE singleton;
  UPDATE app.workspace_usage u SET content_bytes=GREATEST(0,u.content_bytes-r.bytes)
   FROM (SELECT user_id,sum(reserved_bytes) AS bytes FROM app.analysis_requests
         WHERE state='pending' GROUP BY user_id) r WHERE u.user_id=r.user_id;
  UPDATE app.messages SET status='interrupted' WHERE status='pending';
  UPDATE app.analysis_requests SET state='interrupted',reserved_bytes=0,finished_at=now()
   WHERE state='pending';
 END IF;
END;
$$;
COMMIT;
