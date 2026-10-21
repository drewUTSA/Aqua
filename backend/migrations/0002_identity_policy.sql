-- Additive P03 cutover: 0001 remains immutable after P02 deployment.
ALTER TABLE app.users ADD COLUMN picture text NOT NULL DEFAULT '' CHECK (length(picture) <= 1024);
ALTER TABLE app.external_identities
 ADD COLUMN observed_email_key text NOT NULL DEFAULT '' CHECK (length(observed_email_key) <= 320),
 ADD COLUMN email_authoritative boolean NOT NULL DEFAULT false,
 ADD CONSTRAINT identities_owner_id UNIQUE(user_id,id);
ALTER TABLE app.dataset_grants
 ADD COLUMN approval_kind text NOT NULL DEFAULT 'operator'
 CHECK (approval_kind IN ('operator','google_subject','google_email')),
 ADD COLUMN approval_identity_id uuid,
 ADD COLUMN approval_evidence text NOT NULL DEFAULT '' CHECK (length(approval_evidence) <= 320),
 ADD CONSTRAINT grant_approval_provenance CHECK
 ((approval_kind='operator' AND approval_identity_id IS NULL) OR
  (approval_kind IN ('google_subject','google_email') AND approval_identity_id IS NOT NULL AND approval_evidence<>'')),
 ADD CONSTRAINT grant_identity_owner FOREIGN KEY(user_id,approval_identity_id)
 REFERENCES app.external_identities(user_id,id);
CREATE FUNCTION app.advance_grant_version() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,app AS $$
 BEGIN
  NEW.version := OLD.version + 1;
  RETURN NEW;
 END;
$$;
CREATE TRIGGER advance_grant_version BEFORE UPDATE ON app.dataset_grants
 FOR EACH ROW EXECUTE FUNCTION app.advance_grant_version();
CREATE TABLE app.auth_admission (
 scope text NOT NULL CHECK (scope IN ('challenge:global','challenge:peer','login:global','login:peer','login:account')),
 key_digest bytea NOT NULL CHECK (octet_length(key_digest)=32),
 hits integer NOT NULL CHECK (hits BETWEEN 1 AND 300),
 expires_at timestamptz NOT NULL,
 PRIMARY KEY(scope,key_digest)
);
CREATE INDEX auth_admission_expiry ON app.auth_admission(expires_at,scope,key_digest);
CREATE INDEX challenges_session ON app.auth_challenges(session_id) WHERE session_id IS NOT NULL;
-- Idle-expired records may remain until absolute expiry. Seek directly to the
-- live part of one user's current epoch, then inspect at most the session cap.
CREATE INDEX sessions_owner_epoch_idle ON app.sessions(user_id,auth_epoch,idle_expires_at)
 INCLUDE(id) WHERE revoked_at IS NULL;
GRANT SELECT,INSERT,UPDATE,DELETE ON app.auth_admission TO aqua_app_runtime;
