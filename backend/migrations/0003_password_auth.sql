-- P04 is additive: pre-existing identity, grants and migration checksums stay intact.
ALTER TABLE app.auth_challenges DROP CONSTRAINT auth_challenges_purpose_check;
ALTER TABLE app.auth_challenges ADD CONSTRAINT auth_challenges_purpose_check
 CHECK (purpose IN ('google_login','registration','verify_email','password_reset','link','reauth','password_action'));
ALTER TABLE app.auth_challenges ADD COLUMN password_auth_epoch bigint
 CHECK (password_auth_epoch IS NULL OR password_auth_epoch>=0);
ALTER TABLE app.auth_challenges ADD CONSTRAINT password_challenge_provenance CHECK
 ((purpose NOT IN ('verify_email','password_reset')) OR
  (purpose='verify_email' AND user_id IS NULL AND target_email_key IS NOT NULL AND password_auth_epoch IS NULL) OR
  (purpose='password_reset' AND user_id IS NOT NULL AND target_email_key IS NOT NULL AND password_auth_epoch IS NOT NULL));
CREATE INDEX challenges_password_target ON app.auth_challenges(purpose,target_email_key,expires_at)
 INCLUDE(id) WHERE consumed_at IS NULL AND purpose IN ('verify_email','password_reset');
CREATE TABLE app.password_admission (
 scope text NOT NULL CHECK(scope IN ('login:global','login:peer','login:address','mail:global','mail:peer','mail:address','consume:global','consume:peer')),
 key_digest bytea NOT NULL CHECK(octet_length(key_digest)=32),
 hits integer NOT NULL CHECK(hits BETWEEN 1 AND 300),
 expires_at timestamptz NOT NULL, PRIMARY KEY(scope,key_digest)
);
CREATE INDEX password_admission_expiry ON app.password_admission(expires_at,scope,key_digest);
-- Slots deliberately do not expire on a timer: a paused worker can still hold
-- Argon2 memory. A crash fails closed; maintenance stops workers before reset.
CREATE TABLE app.password_hash_slots (
 id uuid PRIMARY KEY, started_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
GRANT SELECT,INSERT,UPDATE,DELETE ON app.password_admission,app.password_hash_slots TO aqua_app_runtime;
-- Caller executes this fragment as aqua_app_owner within migration 0003.
CREATE TABLE app.account_mail (
 id uuid PRIMARY KEY,
 purpose text NOT NULL CHECK (purpose IN ('verify_email','reset_password','password_changed')),
 recipient_digest bytea NOT NULL CHECK (octet_length(recipient_digest)=32),
 ciphertext bytea NOT NULL CHECK (octet_length(ciphertext) BETWEEN 30 AND 4096),
 challenge_id uuid REFERENCES app.auth_challenges(id) ON DELETE CASCADE,
 created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
 state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','sending','sent','failed','expired')),
 attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
 available_at timestamptz NOT NULL DEFAULT now(), first_attempt_at timestamptz,
 lease_id uuid, lease_expires_at timestamptz,
 CHECK (expires_at > created_at AND expires_at <= created_at + interval '24 hours 1 minute'),
 CHECK (purpose='password_changed' OR challenge_id IS NOT NULL),
 CHECK ((state='sending')=(lease_id IS NOT NULL AND lease_expires_at IS NOT NULL))
);
CREATE INDEX account_mail_due ON app.account_mail(available_at,id) WHERE state IN ('pending','sending');
CREATE INDEX account_mail_purpose_due ON app.account_mail(purpose,available_at,id) WHERE state IN ('pending','sending');
CREATE INDEX account_mail_expiry ON app.account_mail(expires_at,id);
CREATE INDEX account_mail_challenge ON app.account_mail(challenge_id) WHERE challenge_id IS NOT NULL;
CREATE TABLE app.account_mail_control (
 singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
 last_attempt_at timestamptz NOT NULL DEFAULT (now()-interval '2 seconds'),
 lease_id uuid, lease_expires_at timestamptz,
 hour_started_at timestamptz NOT NULL DEFAULT now(), hour_hits integer NOT NULL DEFAULT 0 CHECK (hour_hits BETWEEN 0 AND 20),
 verify_hour_hits integer NOT NULL DEFAULT 0 CHECK (verify_hour_hits BETWEEN 0 AND 5),
 verify_day_hits integer NOT NULL DEFAULT 0 CHECK (verify_day_hits BETWEEN 0 AND 20),
 reset_hour_hits integer NOT NULL DEFAULT 0 CHECK (reset_hour_hits BETWEEN 0 AND 5),
 reset_day_hits integer NOT NULL DEFAULT 0 CHECK (reset_day_hits BETWEEN 0 AND 20),
 notice_hour_hits integer NOT NULL DEFAULT 0 CHECK (notice_hour_hits BETWEEN 0 AND 10),
 notice_day_hits integer NOT NULL DEFAULT 0 CHECK (notice_day_hits BETWEEN 0 AND 20),
 day_started_at timestamptz NOT NULL DEFAULT now(), day_hits integer NOT NULL DEFAULT 0 CHECK (day_hits BETWEEN 0 AND 60)
);
INSERT INTO app.account_mail_control(singleton) VALUES (true);
GRANT SELECT,INSERT,UPDATE,DELETE ON app.account_mail TO aqua_app_runtime;
GRANT SELECT,UPDATE ON app.account_mail_control TO aqua_app_runtime;

-- Recipient issuance history is independent of token/job retention. Never evict
-- a live row to grant a new allowance; bounded cleanup expires whole windows.
CREATE TABLE app.mail_recipient_budget (
 purpose text NOT NULL CHECK (purpose IN ('verify_email','reset_password')),
 recipient_digest bytea NOT NULL CHECK (octet_length(recipient_digest)=32),
 issued_at timestamptz[] NOT NULL CHECK (cardinality(issued_at) BETWEEN 1 AND 3 AND array_ndims(issued_at)=1 AND array_position(issued_at,NULL) IS NULL),
 last_queued_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
 PRIMARY KEY(purpose,recipient_digest)
);
CREATE INDEX mail_recipient_expiry ON app.mail_recipient_budget(expires_at,purpose,recipient_digest);
CREATE INDEX account_mail_recipient_active ON app.account_mail(purpose,recipient_digest)
 WHERE state IN ('pending','sending');
GRANT SELECT,INSERT,UPDATE,DELETE ON app.mail_recipient_budget TO aqua_app_runtime;
