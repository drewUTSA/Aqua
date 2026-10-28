-- P10a is additive. It does not link/unlink methods, change mailboxes/passwords,
-- revoke sessions, enable notices or alter dataset approval.
ALTER TABLE app.users ADD COLUMN profile_revision bigint NOT NULL DEFAULT 1
 CHECK(profile_revision BETWEEN 1 AND 9007199254740991);
-- Tombstones preserve dataset-grant provenance. P10a has no unlink route.
-- A later unlink must revoke all sessions/epoch and derived grants atomically.
ALTER TABLE app.external_identities
 ADD COLUMN is_active boolean NOT NULL DEFAULT true,
 ADD COLUMN inactive_at timestamptz,
 ADD COLUMN revision bigint NOT NULL DEFAULT 1 CHECK(revision BETWEEN 1 AND 9007199254740991),
 ADD CONSTRAINT identity_active_state CHECK(is_active = (inactive_at IS NULL));
CREATE INDEX identities_owner_active ON app.external_identities(user_id,linked_at,id) WHERE is_active;

-- Preserve old unbound challenges, but never admit one to the new protocol.
ALTER TABLE app.auth_challenges
 ADD COLUMN account_operation text CHECK(account_operation IN
  ('email_change','password_change','google_link','google_unlink','session_revoke','sessions_revoke_all')),
 ADD COLUMN account_target_digest bytea CHECK(octet_length(account_target_digest)=32),
 ADD COLUMN account_auth_epoch bigint CHECK(account_auth_epoch>=0),
 ADD CONSTRAINT account_challenge_binding CHECK
  ((account_operation IS NULL AND account_target_digest IS NULL AND account_auth_epoch IS NULL) OR
   (purpose='reauth' AND user_id IS NOT NULL AND session_id IS NOT NULL AND binding_digest IS NOT NULL
    AND account_operation IS NOT NULL AND account_target_digest IS NOT NULL AND account_auth_epoch IS NOT NULL
    AND expires_at<=created_at+interval '300 seconds'));
CREATE INDEX challenges_account_live ON app.auth_challenges(user_id,expires_at,id)
 WHERE account_operation IS NOT NULL;
CREATE INDEX challenges_account_expiry ON app.auth_challenges(expires_at,id)
 WHERE account_operation IS NOT NULL;
ALTER TABLE app.auth_challenges ADD CONSTRAINT challenges_owner_session_id UNIQUE(user_id,session_id,id);

-- No public or internal verifier issues these in P10a. A later authenticated
-- verifier must recheck its exact credential snapshot before inserting a proof.
CREATE TABLE app.account_action_proofs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 user_id uuid NOT NULL REFERENCES app.users(id), session_id uuid NOT NULL,
 challenge_id uuid NOT NULL UNIQUE,
 secret_digest bytea NOT NULL UNIQUE CHECK(octet_length(secret_digest)=32),
 auth_epoch bigint NOT NULL CHECK(auth_epoch>=0),
 operation text NOT NULL CHECK(operation IN
  ('email_change','password_change','google_link','google_unlink','session_revoke','sessions_revoke_all')),
 target_digest bytea NOT NULL CHECK(octet_length(target_digest)=32),
 method text NOT NULL CHECK(method IN ('password','google')),
 external_identity_id uuid, password_changed_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), expires_at timestamptz NOT NULL,
 consumed_at timestamptz,
 CHECK(expires_at>created_at AND expires_at<=created_at+interval '300 seconds'),
 CHECK((method='google' AND external_identity_id IS NOT NULL AND password_changed_at IS NULL) OR
       (method='password' AND external_identity_id IS NULL AND password_changed_at IS NOT NULL)),
 FOREIGN KEY(user_id,session_id) REFERENCES app.sessions(user_id,id),
 FOREIGN KEY(user_id,session_id,challenge_id) REFERENCES app.auth_challenges(user_id,session_id,id) ON DELETE CASCADE,
 FOREIGN KEY(user_id,external_identity_id) REFERENCES app.external_identities(user_id,id)
);
CREATE INDEX action_proofs_owner ON app.account_action_proofs(user_id,expires_at,id);
CREATE INDEX action_proofs_expiry ON app.account_action_proofs(expires_at,id);
GRANT SELECT,INSERT,UPDATE,DELETE ON app.account_action_proofs TO aqua_app_runtime;

-- Reuse the existing bounded durable auth admission implementation. Action
-- budgets are separate from login/recovery, and cannot be chosen by clients.
ALTER TABLE app.auth_admission DROP CONSTRAINT auth_admission_scope_check;
ALTER TABLE app.auth_admission ADD CONSTRAINT auth_admission_scope_check CHECK(scope IN
 ('challenge:global','challenge:peer','login:global','login:peer','login:account','action:global','action:account'));
