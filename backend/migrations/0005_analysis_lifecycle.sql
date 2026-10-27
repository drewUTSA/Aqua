-- Private bounded execution metadata; applied migrations 0001-0004 stay immutable.
ALTER TABLE app.analysis_requests DROP CONSTRAINT analysis_requests_state_check;
ALTER TABLE app.analysis_requests ADD CONSTRAINT analysis_requests_state_check
 CHECK(state IN ('pending','queued','running','cancelling','complete','error','cancelled','interrupted','expired'));
ALTER TABLE app.messages DROP CONSTRAINT messages_status_check;
ALTER TABLE app.messages ADD CONSTRAINT messages_status_check
 CHECK(status IN ('pending','complete','error','cancelled','interrupted','expired'));

-- A schema-4 synchronous request has no recoverable worker. Fence it once.
WITH released AS (
 SELECT user_id,sum(reserved_bytes) AS amount FROM app.analysis_requests
 WHERE state='pending' GROUP BY user_id
), previous AS (
 SELECT u.user_id,u.content_bytes,least(u.content_bytes,r.amount) AS delta
 FROM app.workspace_usage u JOIN released r USING(user_id)
), changed AS (
 UPDATE app.workspace_usage u SET content_bytes=u.content_bytes-p.delta
 FROM previous p WHERE u.user_id=p.user_id RETURNING p.delta
)
UPDATE app.workspace_totals SET content_bytes=greatest(0,content_bytes-(SELECT coalesce(sum(delta),0) FROM changed)) WHERE singleton;
UPDATE app.messages SET status='interrupted' WHERE status='pending';
UPDATE app.analysis_requests SET state='interrupted',reserved_bytes=0,finished_at=clock_timestamp() WHERE state='pending';

CREATE TABLE app.analysis_jobs (
 id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES app.users(id), request_id uuid,
 session_digest bytea NOT NULL CHECK(octet_length(session_digest)=32), auth_epoch bigint NOT NULL CHECK(auth_epoch>=0),
 dataset_key text NOT NULL CHECK(length(dataset_key) BETWEEN 1 AND 128), grant_version bigint NOT NULL CHECK(grant_version>=0),
 question text NOT NULL DEFAULT '' CHECK(length(question)<=2000 AND octet_length(question)<=8000),
 model text NOT NULL CHECK(model IN ('gemini','ollama')),
 context jsonb NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(context)='array' AND octet_length(context::text)<=16384),
 context_digest bytea NOT NULL CHECK(octet_length(context_digest)=32), content_bytes integer NOT NULL DEFAULT 0 CHECK(content_bytes BETWEEN 0 AND 300000),
 state text NOT NULL CHECK(state IN ('queued','running','cancelling','complete','error','cancelled','interrupted','expired')),
 stage text NOT NULL CHECK(stage IN ('queued','context','schema','retrieval','generating','validating','executing','summarizing','persisting','cancelling','complete','error','cancelled','interrupted','expired')),
 version bigint NOT NULL DEFAULT 1 CHECK(version>0), last_event_sequence integer NOT NULL DEFAULT 0 CHECK(last_event_sequence BETWEEN 0 AND 32),
 cancel_requested boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT statement_timestamp(), deadline_at timestamptz NOT NULL,
 lease_token bigint NOT NULL DEFAULT 0 CHECK(lease_token>=0), lease_owner uuid, lease_until timestamptz,
 physical_until timestamptz, started_at timestamptz, finished_at timestamptz,
 response jsonb CHECK(response IS NULL OR (jsonb_typeof(response)='object' AND octet_length(response::text)<=262144)),
 http_status integer CHECK(http_status BETWEEN 200 AND 599),
 UNIQUE(user_id,id), UNIQUE(request_id),
 FOREIGN KEY(user_id,request_id) REFERENCES app.analysis_requests(user_id,id),
 CHECK(deadline_at>created_at AND deadline_at<=created_at+interval '120 seconds'),
 CHECK(request_id IS NULL OR id=request_id)
);
CREATE INDEX analysis_jobs_queue ON app.analysis_jobs(created_at,id) WHERE state='queued';
CREATE INDEX analysis_jobs_owner_state ON app.analysis_jobs(user_id,state,created_at);
CREATE INDEX analysis_jobs_physical ON app.analysis_jobs(physical_until) WHERE physical_until IS NOT NULL;
CREATE INDEX analysis_jobs_legacy_retention ON app.analysis_jobs(finished_at,id) WHERE request_id IS NULL;
CREATE TABLE app.analysis_admission (
 scope text PRIMARY KEY CHECK(length(scope) BETWEEN 1 AND 180),
 units integer NOT NULL CHECK(units BETWEEN 1 AND 120), expires_at timestamptz NOT NULL
);
CREATE TABLE app.analysis_events (
 user_id uuid NOT NULL, request_id uuid NOT NULL, sequence integer NOT NULL CHECK(sequence BETWEEN 1 AND 32),
 version bigint NOT NULL CHECK(version>0),
 state text NOT NULL CHECK(state IN ('queued','running','cancelling','complete','error','cancelled','interrupted','expired')),
 stage text NOT NULL CHECK(stage IN ('queued','context','schema','retrieval','generating','validating','executing','summarizing','persisting','cancelling','complete','error','cancelled','interrupted','expired')),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), PRIMARY KEY(request_id,sequence),
 FOREIGN KEY(user_id,request_id) REFERENCES app.analysis_jobs(user_id,id) ON DELETE CASCADE
);
CREATE INDEX analysis_events_owner_time ON app.analysis_events(user_id,created_at);
CREATE TABLE app.analysis_streams (
 id uuid PRIMARY KEY, user_id uuid NOT NULL, request_id uuid NOT NULL,
 expires_at timestamptz NOT NULL, hard_expires_at timestamptz NOT NULL,
 FOREIGN KEY(user_id,request_id) REFERENCES app.analysis_jobs(user_id,id) ON DELETE CASCADE
);
CREATE INDEX analysis_streams_owner_expiry ON app.analysis_streams(user_id,expires_at);
GRANT SELECT,INSERT,UPDATE,DELETE ON app.analysis_jobs,app.analysis_admission,app.analysis_events,app.analysis_streams TO aqua_app_runtime;
