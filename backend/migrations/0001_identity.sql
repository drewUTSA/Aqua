-- Private identity foundation only. No public endpoints or automatic grants.
CREATE TABLE app.users (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','active','disabled','deleting')),
 display_name text NOT NULL DEFAULT '' CHECK (length(display_name) <= 120),
 auth_epoch bigint NOT NULL DEFAULT 0 CHECK (auth_epoch >= 0),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 deleted_at timestamptz
);
CREATE TABLE app.user_emails (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES app.users(id),
 address text NOT NULL CHECK (length(address) BETWEEN 3 AND 320),
 email_key text NOT NULL UNIQUE CHECK (length(email_key) BETWEEN 3 AND 320),
 verified_at timestamptz, verification_method text CHECK (verification_method IN ('google','email')),
 is_primary boolean NOT NULL DEFAULT false,
 CHECK (NOT is_primary OR verified_at IS NOT NULL)
);
CREATE UNIQUE INDEX one_primary_email ON app.user_emails(user_id) WHERE is_primary;
CREATE INDEX emails_owner ON app.user_emails(user_id);
CREATE TABLE app.external_identities (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES app.users(id),
 provider text NOT NULL CHECK (provider = 'google'),
 issuer text NOT NULL CHECK (issuer = 'https://accounts.google.com'),
 subject text NOT NULL CHECK (length(subject) BETWEEN 1 AND 255),
 linked_at timestamptz NOT NULL DEFAULT now(), last_login_at timestamptz,
 UNIQUE (issuer,subject)
);
CREATE INDEX identities_owner ON app.external_identities(user_id,provider);
CREATE TABLE app.password_credentials (
 user_id uuid PRIMARY KEY REFERENCES app.users(id),
 encoded_hash text NOT NULL CHECK (length(encoded_hash) BETWEEN 32 AND 1024),
 policy_version integer NOT NULL CHECK (policy_version > 0), changed_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE app.sessions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES app.users(id),
 token_digest bytea NOT NULL UNIQUE CHECK (octet_length(token_digest) = 32),
 csrf_digest bytea NOT NULL CHECK (octet_length(csrf_digest) = 32),
 auth_epoch bigint NOT NULL CHECK (auth_epoch >= 0),
 method text NOT NULL CHECK (method IN ('google','password','linked')),
 authenticated_at timestamptz NOT NULL DEFAULT now(), created_at timestamptz NOT NULL DEFAULT now(),
 last_activity_at timestamptz NOT NULL DEFAULT now(),
 idle_expires_at timestamptz NOT NULL, absolute_expires_at timestamptz NOT NULL,
 revoked_at timestamptz, device_label text NOT NULL DEFAULT '' CHECK (length(device_label) <= 120),
 CHECK (absolute_expires_at > created_at AND idle_expires_at > created_at AND idle_expires_at <= absolute_expires_at),
 UNIQUE (user_id,id)
);
CREATE INDEX sessions_owner_active ON app.sessions(user_id,last_activity_at DESC,id) WHERE revoked_at IS NULL;
CREATE INDEX sessions_expiry ON app.sessions(absolute_expires_at);
CREATE TABLE app.auth_challenges (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 purpose text NOT NULL CHECK (purpose IN ('google_login','registration','verify_email','password_reset','link','reauth')),
 user_id uuid REFERENCES app.users(id), session_id uuid,
 secret_digest bytea NOT NULL UNIQUE CHECK (octet_length(secret_digest) = 32),
 binding_digest bytea CHECK (octet_length(binding_digest) = 32),
 target_email_key text CHECK (length(target_email_key) <= 320),
 created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
 consumed_at timestamptz, CHECK (expires_at > created_at),
 FOREIGN KEY (user_id,session_id) REFERENCES app.sessions(user_id,id),
 CHECK (session_id IS NULL OR user_id IS NOT NULL)
);
CREATE INDEX challenges_owner_purpose ON app.auth_challenges(user_id,purpose);
CREATE INDEX challenges_expiry ON app.auth_challenges(expires_at);
CREATE TABLE app.dataset_grants (
 user_id uuid NOT NULL REFERENCES app.users(id),
 dataset_key text NOT NULL CHECK (length(dataset_key) BETWEEN 1 AND 128),
 permission text NOT NULL DEFAULT 'read' CHECK (permission = 'read'),
 version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
 granted_at timestamptz NOT NULL DEFAULT now(), revoked_at timestamptz,
 PRIMARY KEY (user_id,dataset_key)
);
CREATE TABLE app.user_preferences (
 user_id uuid PRIMARY KEY REFERENCES app.users(id), schema_version integer NOT NULL DEFAULT 1 CHECK (schema_version > 0),
 revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
 values jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(values) = 'object' AND octet_length(values::text) <= 65536),
 updated_at timestamptz NOT NULL DEFAULT now()
);
-- Explicit table grants; the runtime never owns or writes the migration ledger.
GRANT SELECT,INSERT,UPDATE,DELETE ON app.users,app.user_emails,app.external_identities,
 app.password_credentials,app.sessions,app.auth_challenges,app.dataset_grants,app.user_preferences TO aqua_app_runtime;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA app FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE aqua_app_owner IN SCHEMA app REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE aqua_app_owner IN SCHEMA app GRANT SELECT ON TABLES TO aqua_app_backup;
