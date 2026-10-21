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
COMMIT;
