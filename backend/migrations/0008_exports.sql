-- P11a additive private output. Never rewrite applied migrations 0001--0007.
ALTER TABLE app.users ADD COLUMN privacy_epoch bigint NOT NULL DEFAULT 1
 CHECK(privacy_epoch BETWEEN 1 AND 9007199254740991);
ALTER TABLE app.auth_challenges DROP CONSTRAINT auth_challenges_account_operation_check;
ALTER TABLE app.auth_challenges ADD CONSTRAINT auth_challenges_account_operation_check CHECK(account_operation IN
 ('email_change','password_change','password_add','google_link','google_unlink','session_revoke','sessions_revoke_all','data_export'));
ALTER TABLE app.account_action_proofs DROP CONSTRAINT account_action_proofs_operation_check;
ALTER TABLE app.account_action_proofs ADD CONSTRAINT account_action_proofs_operation_check CHECK(operation IN
 ('email_change','password_change','password_add','google_link','google_unlink','session_revoke','sessions_revoke_all','data_export'));

CREATE TABLE app.data_exports (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES app.users(id),
 session_id uuid NOT NULL, intent_id uuid NOT NULL,
 scope text NOT NULL CHECK(scope='personal_v1'),
 auth_epoch bigint NOT NULL CHECK(auth_epoch>=0),
 privacy_epoch bigint NOT NULL CHECK(privacy_epoch BETWEEN 1 AND 9007199254740991),
 state text NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','working','ready','expired','failed')),
 created_at timestamptz NOT NULL, expires_at timestamptz NOT NULL, deadline_at timestamptz NOT NULL,
 reserved_bytes integer NOT NULL DEFAULT 33554432 CHECK(reserved_bytes IN(0,33554432)),
 output_bytes integer NOT NULL DEFAULT 0 CHECK(output_bytes BETWEEN 0 AND 33554432),
 chunk_count integer NOT NULL DEFAULT 0 CHECK(chunk_count BETWEEN 0 AND 512),
 sha256 text CHECK(sha256 ~ '^[a-f0-9]{64}$'),
 contains_results boolean NOT NULL DEFAULT false,
 dataset_key text NOT NULL DEFAULT '' CHECK(length(dataset_key)<=128),
 grant_version bigint NOT NULL DEFAULT 0 CHECK(grant_version>=0),
 generation integer NOT NULL DEFAULT 0 CHECK(generation BETWEEN 0 AND 3),
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 3),
 lease_owner uuid, lease_until timestamptz,
 error_code text CHECK(error_code IN ('source_too_large','authority_changed','interrupted','unavailable','encoding_failed')),
 UNIQUE(user_id,id), UNIQUE(user_id,intent_id),
 FOREIGN KEY(user_id,session_id) REFERENCES app.sessions(user_id,id),
 CHECK(expires_at=created_at+interval '1 hour'),
 CHECK(deadline_at=created_at+interval '120 seconds'),
 CHECK((state='working')=(lease_owner IS NOT NULL AND lease_until IS NOT NULL)),
 CHECK((state='ready')=(sha256 IS NOT NULL)),
 CHECK(state<>'ready' OR (reserved_bytes=0 AND output_bytes>0 AND chunk_count>0)),
 CHECK((state='failed')=(error_code IS NOT NULL)),
 CHECK(NOT contains_results OR (length(dataset_key)>0 AND grant_version>0))
);
CREATE UNIQUE INDEX exports_one_live_owner ON app.data_exports(user_id) WHERE state IN ('queued','working','ready');
CREATE INDEX exports_owner_created ON app.data_exports(user_id,created_at DESC,id DESC);
CREATE INDEX exports_queue ON app.data_exports(created_at,id) WHERE state='queued';
CREATE INDEX exports_expiry ON app.data_exports(expires_at,id);
CREATE INDEX exports_session ON app.data_exports(user_id,session_id);

CREATE TABLE app.data_export_chunks (
 user_id uuid NOT NULL, job_id uuid NOT NULL,
 generation integer NOT NULL CHECK(generation BETWEEN 1 AND 3),
 ordinal integer NOT NULL CHECK(ordinal BETWEEN 0 AND 511),
 body bytea NOT NULL CHECK(octet_length(body) BETWEEN 1 AND 65536),
 digest bytea NOT NULL CHECK(octet_length(digest)=32 AND digest=sha256(body)),
 PRIMARY KEY(job_id,generation,ordinal),
 FOREIGN KEY(user_id,job_id) REFERENCES app.data_exports(user_id,id)
);
CREATE INDEX export_chunks_owner ON app.data_export_chunks(user_id,job_id,generation,ordinal);

CREATE TABLE app.privacy_control (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 reserved_bytes bigint NOT NULL DEFAULT 0 CHECK(reserved_bytes>=0),
 stored_bytes bigint NOT NULL DEFAULT 0 CHECK(stored_bytes>=0),
 worker_owner uuid, worker_until timestamptz, worker_job uuid,
 CHECK(reserved_bytes+stored_bytes<=134217728),
 CHECK((worker_owner IS NULL AND worker_until IS NULL AND worker_job IS NULL) OR
       (worker_owner IS NOT NULL AND worker_until IS NOT NULL AND worker_job IS NOT NULL))
);
INSERT INTO app.privacy_control(singleton) VALUES(true);
CREATE TABLE app.privacy_admission (
 scope text NOT NULL CHECK(scope IN ('download:global','download:account')),
 key_digest bytea NOT NULL CHECK(octet_length(key_digest)=32),
 hits integer NOT NULL CHECK(hits BETWEEN 1 AND 20),
 expires_at timestamptz NOT NULL, PRIMARY KEY(scope,key_digest)
);
CREATE INDEX privacy_admission_expiry ON app.privacy_admission(expires_at,scope,key_digest);
GRANT SELECT,INSERT,UPDATE,DELETE ON app.data_exports,app.data_export_chunks,app.privacy_admission TO aqua_app_runtime;
GRANT SELECT,UPDATE ON app.privacy_control TO aqua_app_runtime;
