-- Additive P10c. Applied 0001--0006 are immutable; no startup migration.
ALTER TABLE app.users ADD COLUMN email_revision bigint NOT NULL DEFAULT 1
 CHECK(email_revision BETWEEN 1 AND 9007199254740991);
ALTER TABLE app.account_action_proofs ADD COLUMN external_identity_revision bigint
 CHECK(external_identity_revision BETWEEN 1 AND 9007199254740991);
-- Never bless legacy Google proofs with today's active revision.
UPDATE app.account_action_proofs SET consumed_at=COALESCE(consumed_at,clock_timestamp()) WHERE method='google';
ALTER TABLE app.account_action_proofs ADD CONSTRAINT proof_identity_revision CHECK
 ((method='password' AND external_identity_revision IS NULL) OR
  (method='google' AND (external_identity_revision IS NOT NULL OR consumed_at IS NOT NULL)));
ALTER TABLE app.auth_challenges DROP CONSTRAINT auth_challenges_account_operation_check;
ALTER TABLE app.auth_challenges ADD CONSTRAINT auth_challenges_account_operation_check CHECK(account_operation IN
 ('email_change','password_change','password_add','google_link','google_unlink','session_revoke','sessions_revoke_all'));
ALTER TABLE app.account_action_proofs DROP CONSTRAINT account_action_proofs_operation_check;
ALTER TABLE app.account_action_proofs ADD CONSTRAINT account_action_proofs_operation_check CHECK(operation IN
 ('email_change','password_change','password_add','google_link','google_unlink','session_revoke','sessions_revoke_all'));
ALTER TABLE app.auth_challenges ADD COLUMN account_google_identity_id uuid,
 ADD COLUMN account_google_identity_revision bigint CHECK(account_google_identity_revision BETWEEN 1 AND 9007199254740991),
 ADD CONSTRAINT challenge_google_snapshot CHECK
 ((account_google_identity_id IS NULL AND account_google_identity_revision IS NULL) OR
  (account_operation IS NOT NULL AND account_google_identity_id IS NOT NULL AND account_google_identity_revision IS NOT NULL)),
 ADD CONSTRAINT challenge_google_owner FOREIGN KEY(user_id,account_google_identity_id) REFERENCES app.external_identities(user_id,id);

CREATE TABLE app.account_security_requests (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES app.users(id),
 session_id uuid NOT NULL, auth_epoch bigint NOT NULL CHECK(auth_epoch>=0),
 operation text NOT NULL CHECK(operation IN ('google_link','email_change','password_add')),
 secret_digest bytea NOT NULL UNIQUE CHECK(octet_length(secret_digest)=32),
 binding_digest bytea NOT NULL CHECK(octet_length(binding_digest)=32),
 target_digest bytea NOT NULL CHECK(octet_length(target_digest)=32),
 source_email_id uuid NOT NULL REFERENCES app.user_emails(id),
 source_email_key text NOT NULL CHECK(length(source_email_key) BETWEEN 3 AND 254),
 source_email_revision bigint NOT NULL CHECK(source_email_revision BETWEEN 1 AND 9007199254740991),
 source_google_identity_id uuid, source_google_identity_revision bigint CHECK(source_google_identity_revision BETWEEN 1 AND 9007199254740991),
 target_email_key text CHECK(length(target_email_key) BETWEEN 3 AND 254),
 google_subject text CHECK(length(google_subject) BETWEEN 1 AND 255),
 google_email_key text CHECK(length(google_email_key) BETWEEN 3 AND 320),
 google_email_authoritative boolean NOT NULL DEFAULT false,
 claimed_at timestamptz, verified_at timestamptz, consumed_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), expires_at timestamptz NOT NULL,
 CHECK(expires_at>created_at AND expires_at<=created_at+interval '30 minutes'),
 CHECK(operation<>'google_link' OR expires_at<=created_at+interval '300 seconds'),
 CHECK((operation='google_link' AND target_email_key IS NULL) OR
       (operation IN ('email_change','password_add') AND target_email_key IS NOT NULL)),
 CHECK((verified_at IS NULL AND google_subject IS NULL AND google_email_key IS NULL) OR
       (operation='google_link' AND claimed_at IS NOT NULL AND verified_at IS NOT NULL AND google_subject IS NOT NULL AND google_email_key IS NOT NULL)),
 FOREIGN KEY(user_id,session_id) REFERENCES app.sessions(user_id,id), UNIQUE(user_id,session_id,id)
 ,FOREIGN KEY(user_id,source_google_identity_id) REFERENCES app.external_identities(user_id,id)
 ,CHECK((source_google_identity_id IS NULL)=(source_google_identity_revision IS NULL))
 ,CHECK(operation<>'password_add' OR source_google_identity_id IS NOT NULL)
);
CREATE INDEX security_requests_owner ON app.account_security_requests(user_id,expires_at,id);
CREATE INDEX security_requests_expiry ON app.account_security_requests(expires_at,id);
ALTER TABLE app.auth_challenges ADD COLUMN account_request_id uuid,
 ADD CONSTRAINT challenge_account_request_owner FOREIGN KEY(user_id,session_id,account_request_id)
 REFERENCES app.account_security_requests(user_id,session_id,id) ON DELETE CASCADE;
ALTER TABLE app.auth_challenges DROP CONSTRAINT auth_challenges_purpose_check;
ALTER TABLE app.auth_challenges ADD CONSTRAINT auth_challenges_purpose_check CHECK(purpose IN
 ('google_login','registration','verify_email','password_reset','link','reauth','password_action','email_change_new','email_change_old','password_add'));
ALTER TABLE app.auth_challenges ADD CONSTRAINT account_mail_binding CHECK
 ((purpose NOT IN ('email_change_new','email_change_old','password_add') AND account_request_id IS NULL) OR
  (purpose IN ('email_change_new','email_change_old','password_add') AND user_id IS NOT NULL AND session_id IS NOT NULL AND account_request_id IS NOT NULL
   AND target_email_key IS NOT NULL AND password_auth_epoch IS NOT NULL AND account_operation IS NULL));
CREATE INDEX challenges_account_request ON app.auth_challenges(account_request_id,id) WHERE account_request_id IS NOT NULL;
CREATE UNIQUE INDEX challenge_request_purpose ON app.auth_challenges(account_request_id,purpose) WHERE account_request_id IS NOT NULL;
CREATE INDEX grants_active_identity ON app.dataset_grants(user_id,approval_identity_id,dataset_key)
 WHERE revoked_at IS NULL AND approval_kind IN ('google_subject','google_email');
ALTER TABLE app.account_mail DROP CONSTRAINT account_mail_purpose_check;
ALTER TABLE app.account_mail ADD CONSTRAINT account_mail_purpose_check CHECK(purpose IN
 ('verify_email','reset_password','password_changed','email_change_new','email_change_old','password_add','email_changed','password_added','google_linked','google_unlinked'));
-- The original anonymous check allows only password_changed without a ticket.
ALTER TABLE app.account_mail DROP CONSTRAINT account_mail_check1;
ALTER TABLE app.account_mail ADD CONSTRAINT account_mail_ticket CHECK
 (purpose IN ('password_changed','email_changed','password_added','google_linked','google_unlinked') OR challenge_id IS NOT NULL);
CREATE UNIQUE INDEX account_mail_identity_ticket ON app.account_mail(challenge_id)
 WHERE purpose IN ('email_change_new','email_change_old','password_add');
-- Recipient quota keys deliberately remain only verify_email/reset_password;
-- every new verification purpose shares the original verify_email allowance.
CREATE TABLE app.user_notification_settings (
 user_id uuid PRIMARY KEY REFERENCES app.users(id), revision bigint NOT NULL DEFAULT 1 CHECK(revision BETWEEN 1 AND 9007199254740991),
 in_app_success boolean NOT NULL DEFAULT false,
 preview text NOT NULL DEFAULT 'generic' CHECK(preview IN ('generic','hidden')),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
GRANT SELECT,INSERT,UPDATE,DELETE ON app.account_security_requests,app.user_notification_settings TO aqua_app_runtime;
