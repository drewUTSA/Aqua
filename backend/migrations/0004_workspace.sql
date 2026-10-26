-- Additive private workspace. Applied identity/password migrations stay immutable.
CREATE TABLE app.projects (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES app.users(id),
 name text NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
 revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0), archived boolean NOT NULL DEFAULT false,
 client_request_id uuid NOT NULL, fingerprint bytea NOT NULL CHECK (octet_length(fingerprint)=32),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), updated_at timestamptz NOT NULL DEFAULT clock_timestamp(), deleted_at timestamptz,
 UNIQUE(user_id,id), UNIQUE(user_id,client_request_id)
);
CREATE INDEX projects_owner_activity ON app.projects(user_id,archived,updated_at DESC,id DESC) WHERE deleted_at IS NULL;
CREATE TABLE app.chats (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES app.users(id), project_id uuid,
 title text NOT NULL CHECK (length(title) BETWEEN 1 AND 120),
 revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0), archived boolean NOT NULL DEFAULT false,
 next_message_sequence bigint NOT NULL DEFAULT 1 CHECK (next_message_sequence BETWEEN 1 AND 1001),
 message_count integer NOT NULL DEFAULT 0 CHECK (message_count BETWEEN 0 AND 200),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), last_activity_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 deleted_at timestamptz, UNIQUE(user_id,id),
 FOREIGN KEY(user_id,project_id) REFERENCES app.projects(user_id,id)
);
CREATE INDEX chats_owner_activity ON app.chats(user_id,archived,last_activity_at DESC,id DESC) WHERE deleted_at IS NULL;
CREATE INDEX chats_owner_project ON app.chats(user_id,project_id,last_activity_at DESC,id DESC) WHERE deleted_at IS NULL;
CREATE INDEX chats_owner_title ON app.chats(user_id,lower(title) text_pattern_ops) WHERE deleted_at IS NULL;
CREATE TABLE app.messages (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL, chat_id uuid NOT NULL,
 sequence bigint NOT NULL CHECK (sequence > 0), role text NOT NULL CHECK (role IN ('user','aqua')),
 content text NOT NULL DEFAULT '' CHECK (length(content) <= 2000 AND octet_length(content) <= 8000),
 request_id uuid, reply_to uuid, model_id text NOT NULL DEFAULT '' CHECK (length(model_id) <= 120),
 status text NOT NULL CHECK (status IN ('pending','complete','error','interrupted')),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(user_id,chat_id,id), UNIQUE(chat_id,sequence),
 FOREIGN KEY(user_id,chat_id) REFERENCES app.chats(user_id,id),
 FOREIGN KEY(user_id,chat_id,reply_to) REFERENCES app.messages(user_id,chat_id,id)
);
CREATE INDEX messages_owner_sequence ON app.messages(user_id,chat_id,sequence DESC);
CREATE TABLE app.analysis_requests (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL, chat_id uuid NOT NULL,
 client_request_id uuid NOT NULL, fingerprint bytea NOT NULL CHECK(octet_length(fingerprint)=32),
 input_message_id uuid NOT NULL, reply_message_id uuid NOT NULL, retry_of uuid,
 state text NOT NULL CHECK(state IN ('pending','complete','error','interrupted')),
 reserved_bytes integer NOT NULL DEFAULT 1024 CHECK(reserved_bytes IN (0,1024)),
 requested_model text NOT NULL DEFAULT '' CHECK(length(requested_model)<=120),
 dataset_key text NOT NULL CHECK(length(dataset_key)<=128), grant_version bigint NOT NULL CHECK(grant_version>=0),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), finished_at timestamptz,
 UNIQUE(user_id,id), UNIQUE(user_id,chat_id,id), UNIQUE(user_id,client_request_id),
 FOREIGN KEY(user_id,chat_id) REFERENCES app.chats(user_id,id),
 FOREIGN KEY(user_id,chat_id,input_message_id) REFERENCES app.messages(user_id,chat_id,id),
 FOREIGN KEY(user_id,chat_id,reply_message_id) REFERENCES app.messages(user_id,chat_id,id),
 FOREIGN KEY(user_id,chat_id,retry_of) REFERENCES app.analysis_requests(user_id,chat_id,id)
);
ALTER TABLE app.messages ADD CONSTRAINT messages_request_owner
 FOREIGN KEY(user_id,chat_id,request_id) REFERENCES app.analysis_requests(user_id,chat_id,id) DEFERRABLE INITIALLY DEFERRED;
CREATE TABLE app.visual_results (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL, chat_id uuid NOT NULL, request_id uuid NOT NULL,
 revision bigint NOT NULL DEFAULT 1 CHECK(revision>0), response jsonb NOT NULL,
 generated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(jsonb_typeof(response)='object' AND octet_length(response::text)<=262144),
 UNIQUE(request_id,revision), FOREIGN KEY(user_id,chat_id,request_id) REFERENCES app.analysis_requests(user_id,chat_id,id)
);
CREATE INDEX results_owner_request ON app.visual_results(user_id,chat_id,request_id);
CREATE TABLE app.saved_prompts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES app.users(id),
 label text NOT NULL CHECK(length(label) BETWEEN 1 AND 120),
 prompt text NOT NULL CHECK(length(prompt) BETWEEN 1 AND 2000 AND octet_length(prompt)<=8000),
 pinned boolean NOT NULL DEFAULT false, use_count bigint NOT NULL DEFAULT 0 CHECK(use_count BETWEEN 0 AND 2147483647),
 last_used_at timestamptz, revision bigint NOT NULL DEFAULT 1 CHECK(revision>0),
 client_request_id uuid NOT NULL, fingerprint bytea NOT NULL CHECK(octet_length(fingerprint)=32),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), updated_at timestamptz NOT NULL DEFAULT clock_timestamp(), deleted_at timestamptz,
 UNIQUE(user_id,id), UNIQUE(user_id,client_request_id)
);
CREATE INDEX saved_prompts_owner_activity ON app.saved_prompts(user_id,updated_at DESC,id DESC) WHERE deleted_at IS NULL;
CREATE TABLE app.saved_prompt_uses (
 user_id uuid NOT NULL, prompt_id uuid NOT NULL, client_request_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), PRIMARY KEY(user_id,client_request_id),
 FOREIGN KEY(user_id,prompt_id) REFERENCES app.saved_prompts(user_id,id) ON DELETE CASCADE
);
CREATE TABLE app.workspace_admission (
 user_id uuid PRIMARY KEY REFERENCES app.users(id), hits integer NOT NULL CHECK(hits BETWEEN 1 AND 60),
 expires_at timestamptz NOT NULL
);
CREATE TABLE app.workspace_usage (
 user_id uuid PRIMARY KEY REFERENCES app.users(id),
 content_bytes bigint NOT NULL DEFAULT 0 CHECK(content_bytes BETWEEN 0 AND 16777216)
);
CREATE TABLE app.workspace_totals (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 content_bytes bigint NOT NULL DEFAULT 0 CHECK(content_bytes BETWEEN 0 AND 209715200)
);
INSERT INTO app.workspace_totals(singleton) VALUES(true);
GRANT SELECT,UPDATE ON app.workspace_totals TO aqua_app_runtime;
GRANT SELECT,INSERT,UPDATE,DELETE ON app.projects,app.chats,app.messages,app.analysis_requests,
 app.visual_results,app.saved_prompts,app.saved_prompt_uses,app.workspace_admission,app.workspace_usage TO aqua_app_runtime;
