-- Explicit saved text is a library, never a permission or automatic model input.
CREATE TABLE app.context_notes (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 user_id uuid NOT NULL REFERENCES app.users(id),
 dataset_key text NOT NULL CHECK(dataset_key ~ '^[a-f0-9]{64}$'),
 grant_version bigint NOT NULL CHECK(grant_version>=0),
 kind text NOT NULL CHECK(kind IN ('note','metric_definition')),
 label text NOT NULL,
 body text NOT NULL,
 revision bigint NOT NULL DEFAULT 1 CHECK(revision BETWEEN 1 AND 9007199254740991),
 client_request_id uuid NOT NULL,
 fingerprint bytea NOT NULL CHECK(octet_length(fingerprint)=32),
 content_bytes integer NOT NULL CHECK(content_bytes BETWEEN 0 AND 2560),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 deleted_at timestamptz,
 UNIQUE(user_id,id),
 UNIQUE(user_id,client_request_id),
 CHECK (
   (deleted_at IS NULL
     AND length(label) BETWEEN 1 AND 120 AND octet_length(label)<=512
     AND length(body) BETWEEN 1 AND 2000 AND octet_length(body)<=2048
     AND content_bytes=octet_length(label)+octet_length(body))
   OR
   (deleted_at IS NOT NULL AND label='Deleted context' AND body=''
     AND content_bytes=0 AND fingerprint=decode(repeat('00',32),'hex'))
 )
);
CREATE INDEX context_notes_owner_activity ON app.context_notes(user_id,updated_at DESC,id DESC)
 WHERE deleted_at IS NULL;
GRANT SELECT,INSERT,UPDATE,DELETE ON app.context_notes TO aqua_app_runtime;
