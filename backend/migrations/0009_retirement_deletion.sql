-- P11b/c: additive irreversible intent fences and bounded deletion jobs.
-- Independent retirement authority is installed separately, never by startup.
-- Applied migrations 0001--0008 remain byte-exact.
ALTER TABLE app.users ADD COLUMN history_generation bigint NOT NULL DEFAULT 1
 CHECK(history_generation BETWEEN 1 AND 9007199254740991);
ALTER TABLE app.chats ADD COLUMN history_generation bigint NOT NULL DEFAULT 1
 CHECK(history_generation BETWEEN 1 AND 9007199254740991);
ALTER TABLE app.analysis_jobs ADD COLUMN history_generation bigint NOT NULL DEFAULT 1
 CHECK(history_generation BETWEEN 1 AND 9007199254740991);
CREATE INDEX chats_owner_generation ON app.chats(user_id,history_generation,id);
CREATE INDEX analysis_jobs_owner_generation ON app.analysis_jobs(user_id,history_generation,id);

ALTER TABLE app.auth_challenges DROP CONSTRAINT auth_challenges_account_operation_check;
ALTER TABLE app.auth_challenges ADD CONSTRAINT auth_challenges_account_operation_check CHECK(account_operation IN
 ('email_change','password_change','password_add','google_link','google_unlink','session_revoke','sessions_revoke_all','data_export','history_delete','account_delete'));
ALTER TABLE app.account_action_proofs DROP CONSTRAINT account_action_proofs_operation_check;
ALTER TABLE app.account_action_proofs ADD CONSTRAINT account_action_proofs_operation_check CHECK(operation IN
 ('email_change','password_change','password_add','google_link','google_unlink','session_revoke','sessions_revoke_all','data_export','history_delete','account_delete'));

CREATE TABLE app.retirement_intents (
 installation_id uuid NOT NULL, user_id uuid NOT NULL, intent_id uuid NOT NULL,
 job_id uuid NOT NULL UNIQUE, scope text NOT NULL CHECK(scope IN ('chat_history_v1','account_v1')),
 created_at timestamptz NOT NULL CHECK(isfinite(created_at)),
 history_floor bigint NOT NULL CHECK(history_floor BETWEEN 2 AND 9007199254740991),
 privacy_floor bigint NOT NULL CHECK(privacy_floor BETWEEN 2 AND 9007199254740991),
 auth_floor bigint NOT NULL CHECK(auth_floor BETWEEN 0 AND 9007199254740991),
 account_closed boolean NOT NULL,
 fingerprint_count integer CHECK(fingerprint_count BETWEEN 0 AND 100000),
 fingerprint_root bytea CHECK(octet_length(fingerprint_root)=32),
 authority_sequence bigint CHECK(authority_sequence BETWEEN 1 AND 250000),
 event_digest bytea CHECK(octet_length(event_digest)=32),
 checkpointed_at timestamptz CHECK(isfinite(checkpointed_at) AND checkpointed_at>=created_at),
 PRIMARY KEY(installation_id,user_id,intent_id),
 UNIQUE(installation_id,intent_id),
 CHECK(account_closed=(scope='account_v1')),
 CHECK(NOT account_closed OR auth_floor>=1),
 CHECK((fingerprint_count IS NULL AND fingerprint_root IS NULL)
    OR (fingerprint_count IS NOT NULL AND fingerprint_root IS NOT NULL AND
       ((scope='chat_history_v1' AND fingerprint_count=0 AND fingerprint_root=sha256(decode('415155413a7265746972656d656e742d70616765733a763100','hex')))
        OR (scope='account_v1' AND fingerprint_count>=1)))),
 CHECK(authority_sequence IS NULL OR fingerprint_count IS NOT NULL),
 CHECK((authority_sequence IS NULL AND event_digest IS NULL AND checkpointed_at IS NULL)
    OR (authority_sequence IS NOT NULL AND event_digest IS NOT NULL AND checkpointed_at IS NOT NULL))
);
-- Intentionally NO FK to users/visible jobs: deletion and job expiry must leave
-- this minimal immutable idempotence fence. No payload, email, subject, session,
-- proof, arbitrary error, active-content counter or expiry is stored here.
-- Runtime must not DELETE/TRUNCATE/expire these rows. Protected restore
-- reconciliation reinserts exactly these original metadata from authority.

CREATE FUNCTION app.immutable_retirement_intent() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,app AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='retirement_intent_immutable';
 END IF;
 IF (NEW.installation_id,NEW.user_id,NEW.intent_id,NEW.job_id,NEW.scope,NEW.created_at,
     NEW.history_floor,NEW.privacy_floor,NEW.auth_floor,NEW.account_closed)
    IS DISTINCT FROM
    (OLD.installation_id,OLD.user_id,OLD.intent_id,OLD.job_id,OLD.scope,OLD.created_at,
     OLD.history_floor,OLD.privacy_floor,OLD.auth_floor,OLD.account_closed)
 OR (OLD.authority_sequence IS NOT NULL AND
    (NEW.authority_sequence,NEW.event_digest,NEW.checkpointed_at) IS DISTINCT FROM
    (OLD.authority_sequence,OLD.event_digest,OLD.checkpointed_at))
 OR (OLD.fingerprint_count IS NOT NULL AND
    (NEW.fingerprint_count,NEW.fingerprint_root) IS DISTINCT FROM
    (OLD.fingerprint_count,OLD.fingerprint_root)) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='retirement_intent_immutable';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER retirement_intent_immutable BEFORE UPDATE OR DELETE ON app.retirement_intents
 FOR EACH ROW EXECUTE FUNCTION app.immutable_retirement_intent();
REVOKE ALL ON app.retirement_intents FROM PUBLIC,aqua_app_runtime;
GRANT SELECT,INSERT,UPDATE ON app.retirement_intents TO aqua_app_runtime;
CREATE UNIQUE INDEX retirement_intents_authority_sequence ON app.retirement_intents(authority_sequence) WHERE authority_sequence IS NOT NULL;
-- The migration owner retains restore privileges. The runtime role has no
-- TRUNCATE/DELETE/DDL. Final merger must preserve exact backup grants and include
-- this table in its full restore comparator, role/catalog tests and bounded
-- 250000 permanent-intent admission counter under the existing privacy guard.

ALTER TABLE app.auth_challenges ADD COLUMN account_privacy_epoch bigint
 CHECK(account_privacy_epoch BETWEEN 1 AND 9007199254740991);
ALTER TABLE app.auth_challenges ADD COLUMN account_history_generation bigint
 CHECK(account_history_generation BETWEEN 1 AND 9007199254740991);
ALTER TABLE app.account_action_proofs ADD COLUMN privacy_epoch bigint
 CHECK(privacy_epoch BETWEEN 1 AND 9007199254740991);
ALTER TABLE app.account_action_proofs ADD COLUMN history_generation bigint
 CHECK(history_generation BETWEEN 1 AND 9007199254740991);
-- Replace existing operation allowlists additively with history_delete and
-- account_delete in the single merger; no other existing operation disappears.
ALTER TABLE app.auth_challenges ADD CONSTRAINT retirement_challenge_snapshots CHECK(
 (account_operation IN ('history_delete','account_delete')) IS NOT TRUE
 OR (account_privacy_epoch IS NOT NULL AND account_history_generation IS NOT NULL));
ALTER TABLE app.account_action_proofs ADD CONSTRAINT retirement_proof_snapshots CHECK(
 operation NOT IN ('history_delete','account_delete')
 OR (privacy_epoch IS NOT NULL AND history_generation IS NOT NULL));
-- Existing operations may leave the new columns NULL. New destructive
-- operations capture these under the current user guard on challenge creation,
-- recheck on claim/issuance and consume, alongside unchanged existing auth,
-- credential/revision/session/intent digest snapshots. A body-supplied floor is
-- never accepted. No proof is consumed again for an already immutable intent.

-- The temporary ticket binds only minimal original-job metadata, never content.
-- No FK to account/session: completed account purges must remove those rows.
CREATE TABLE app.deletion_jobs (
 id uuid PRIMARY KEY, user_id uuid NOT NULL, intent_id uuid NOT NULL UNIQUE,
 installation_id uuid NOT NULL, scope text NOT NULL CHECK(scope IN ('chat_history_v1','account_v1')),
 state text NOT NULL DEFAULT 'awaiting_authority' CHECK(state IN ('awaiting_authority','accepted','purging','complete')),
 created_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
 receipt_expires_at timestamptz NOT NULL,
 receipt_revoked_at timestamptz,
 origin_absolute_expires_at timestamptz NOT NULL,
 origin_session_id uuid NOT NULL, origin_session_digest bytea NOT NULL CHECK(octet_length(origin_session_digest)=32),
 receipt_digest bytea NOT NULL CHECK(octet_length(receipt_digest)=32),
 mail_recipients bytea NOT NULL DEFAULT '' CHECK(octet_length(mail_recipients)<=32000 AND octet_length(mail_recipients)%32=0),
 history_floor bigint NOT NULL CHECK(history_floor BETWEEN 2 AND 9007199254740991),
 privacy_floor bigint NOT NULL CHECK(privacy_floor BETWEEN 2 AND 9007199254740991),
 auth_floor bigint NOT NULL CHECK(auth_floor BETWEEN 0 AND 9007199254740991),
 account_closed boolean NOT NULL, manifest bytea NOT NULL,
 authority_sequence bigint CHECK(authority_sequence BETWEEN 1 AND 250000),
 authority_digest bytea CHECK(octet_length(authority_digest)=32),
 checkpointed_at timestamptz, completed_at timestamptz,
 lease_owner uuid, lease_generation bigint NOT NULL DEFAULT 0 CHECK(lease_generation>=0), lease_until timestamptz,
 purged_batches bigint NOT NULL DEFAULT 0 CHECK(purged_batches>=0),
 UNIQUE(user_id,id), UNIQUE(user_id,intent_id),
 CHECK(account_closed=(scope='account_v1')),
 CHECK(origin_absolute_expires_at>created_at),
 CHECK(receipt_expires_at=least(created_at+interval '600 seconds',origin_absolute_expires_at)),
 CHECK(expires_at=created_at+interval '1 hour'),
 CHECK(octet_length(manifest) BETWEEN 0 AND 33554432),
 CHECK((authority_sequence IS NULL AND authority_digest IS NULL AND checkpointed_at IS NULL)
    OR (authority_sequence IS NOT NULL AND authority_digest IS NOT NULL AND checkpointed_at IS NOT NULL)),
 CHECK((state='awaiting_authority')=(authority_sequence IS NULL AND authority_digest IS NULL AND checkpointed_at IS NULL)),
 CHECK((state='complete')=(completed_at IS NOT NULL)),
 CHECK((lease_owner IS NULL)=(lease_until IS NULL))
);
CREATE UNIQUE INDEX deletion_one_live_owner ON app.deletion_jobs(user_id) WHERE state<>'complete';
CREATE INDEX deletion_jobs_queue ON app.deletion_jobs(state,created_at,id) WHERE state<>'complete';
CREATE INDEX deletion_jobs_owner ON app.deletion_jobs(user_id,created_at DESC,id DESC);
CREATE INDEX deletion_jobs_receipt ON app.deletion_jobs(origin_session_digest,intent_id);
CREATE INDEX deletion_jobs_expiry ON app.deletion_jobs(expires_at,id);

CREATE FUNCTION app.immutable_deletion_job() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,app AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  IF OLD.state<>'complete' OR OLD.expires_at>clock_timestamp() THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='deletion_job_not_retired';
  END IF;
  RETURN OLD;
 END IF;
 IF (NEW.id,NEW.user_id,NEW.intent_id,NEW.installation_id,NEW.scope,NEW.created_at,NEW.expires_at,
     NEW.receipt_expires_at,NEW.origin_absolute_expires_at,NEW.origin_session_id,
     NEW.origin_session_digest,NEW.receipt_digest,NEW.mail_recipients,NEW.history_floor,NEW.privacy_floor,NEW.auth_floor,NEW.account_closed)
    IS DISTINCT FROM
    (OLD.id,OLD.user_id,OLD.intent_id,OLD.installation_id,OLD.scope,OLD.created_at,OLD.expires_at,
     OLD.receipt_expires_at,OLD.origin_absolute_expires_at,OLD.origin_session_id,
     OLD.origin_session_digest,OLD.receipt_digest,OLD.mail_recipients,OLD.history_floor,OLD.privacy_floor,OLD.auth_floor,OLD.account_closed)
 OR (OLD.authority_sequence IS NOT NULL AND
     (NEW.authority_sequence,NEW.authority_digest,NEW.checkpointed_at) IS DISTINCT FROM
     (OLD.authority_sequence,OLD.authority_digest,OLD.checkpointed_at))
 OR (OLD.receipt_revoked_at IS NOT NULL AND NEW.receipt_revoked_at IS DISTINCT FROM OLD.receipt_revoked_at)
 OR (NEW.manifest IS DISTINCT FROM OLD.manifest AND
     (octet_length(NEW.manifest)<>0 OR NEW.state NOT IN ('purging','complete')))
 OR (CASE NEW.state WHEN 'awaiting_authority' THEN 0 WHEN 'accepted' THEN 1 WHEN 'purging' THEN 2 ELSE 3 END
     < CASE OLD.state WHEN 'awaiting_authority' THEN 0 WHEN 'accepted' THEN 1 WHEN 'purging' THEN 2 ELSE 3 END) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='deletion_job_immutable';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER deletion_job_immutable BEFORE UPDATE OR DELETE ON app.deletion_jobs
 FOR EACH ROW EXECUTE FUNCTION app.immutable_deletion_job();

CREATE TABLE app.retirement_control (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 permanent_intents integer NOT NULL DEFAULT 0 CHECK(permanent_intents BETWEEN 0 AND 250000),
 manifest_bytes bigint NOT NULL DEFAULT 0 CHECK(manifest_bytes BETWEEN 0 AND 33554432)
 ,recovery_required boolean NOT NULL DEFAULT false
 ,authority_installed boolean NOT NULL DEFAULT false
);
INSERT INTO app.retirement_control(singleton) VALUES(true);
CREATE FUNCTION app.persistent_retirement_installation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,app AS $$
BEGIN
 IF OLD.authority_installed AND NOT NEW.authority_installed THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='retirement_installation_permanent';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER retirement_installation_permanent BEFORE UPDATE ON app.retirement_control
 FOR EACH ROW EXECUTE FUNCTION app.persistent_retirement_installation();
CREATE TABLE app.deletion_admission (
 scope text NOT NULL CHECK(scope IN ('metadata:global','metadata:receipt')),
 key_digest bytea NOT NULL CHECK(octet_length(key_digest)=32),
 hits integer NOT NULL CHECK(hits BETWEEN 1 AND 120),expires_at timestamptz NOT NULL,
 PRIMARY KEY(scope,key_digest)
);
CREATE INDEX deletion_admission_expiry ON app.deletion_admission(expires_at,scope,key_digest);
GRANT SELECT,INSERT,UPDATE,DELETE ON app.deletion_jobs,app.deletion_admission TO aqua_app_runtime;
GRANT SELECT,UPDATE ON app.retirement_control TO aqua_app_runtime;
GRANT SELECT ON app.retirement_intents,app.deletion_jobs,app.retirement_control,app.deletion_admission TO aqua_app_backup;
