-- Apply ONLY to a recovered app database before reconnecting the application.
-- Recovered cookies and outstanding recovery links must not regain validity.
BEGIN;
SET LOCAL ROLE aqua_app_owner;
UPDATE app.users SET auth_epoch = auth_epoch + 1;
UPDATE app.sessions SET revoked_at = now() WHERE revoked_at IS NULL;
UPDATE app.auth_challenges SET consumed_at = now() WHERE consumed_at IS NULL;
COMMIT;
