"""Exercise logical recovery only inside the disposable synthetic PG container."""

import hashlib
from pathlib import Path
from collections.abc import Callable


def verify(docker: Callable, pg: str) -> dict:
    def sql(database: str, statement: bytes) -> bytes:
        return docker(
            "exec",
            "-i",
            pg,
            "psql",
            "-X",
            "-A",
            "-t",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            "-d",
            database,
            data=statement,
        )

    sql(
        "aqua_app",
        b"""
SET ROLE aqua_app_runtime;
INSERT INTO app.users(id,status,display_name) VALUES ('00000000-0000-0000-0000-000000000001','active','Synthetic recovery');
INSERT INTO app.sessions(user_id,token_digest,csrf_digest,auth_epoch,method,idle_expires_at,absolute_expires_at)
 VALUES ('00000000-0000-0000-0000-000000000001',decode(repeat('ab',32),'hex'),decode(repeat('cd',32),'hex'),0,'google',now()+interval '10 minutes',now()+interval '1 hour');
""",
    )
    # Seed schema-3 work independently of whichever fixture ran last. A
    # restored instance must not inherit abandoned hash slots or replay mail.
    sql(
        "aqua_app",
        b"SET ROLE aqua_app_owner; INSERT INTO app.password_hash_slots(id) VALUES ('a78c4e72-c149-4f85-80f1-422cd0637eaa'); INSERT INTO app.account_mail(id,purpose,recipient_digest,ciphertext,expires_at) VALUES ('f4d6b61d-11be-4510-bca3-0521dd724aaa','password_changed',decode(repeat('00',32),'hex'),decode(repeat('ab',30),'hex'),now()+interval '1 hour'); UPDATE app.account_mail_control SET lease_id='5da38ab6-643a-4152-93b5-894c4f8a8651',lease_expires_at=now()+interval '1 minute' WHERE singleton;",
    )
    # Recovery must preserve spent anti-spam history rather than creating a new
    # sending allowance when restored pending proofs/jobs are invalidated.
    sql(
        "aqua_app",
        b"SET ROLE aqua_app_runtime; INSERT INTO app.mail_recipient_budget(purpose,recipient_digest,issued_at,last_queued_at,expires_at) VALUES ('verify_email',decode(repeat('ef',32),'hex'),ARRAY[now()-interval '18 minutes',now()-interval '12 minutes',now()-interval '6 minutes'],now()-interval '6 minutes',now()+interval '24 hours') ON CONFLICT(purpose,recipient_digest) DO UPDATE SET issued_at=EXCLUDED.issued_at,last_queued_at=EXCLUDED.last_queued_at,expires_at=EXCLUDED.expires_at;",
    )
    recipient_sql = b"SELECT issued_at,last_queued_at,expires_at FROM app.mail_recipient_budget WHERE purpose='verify_email' AND recipient_digest=decode(repeat('ef',32),'hex'); SELECT has_table_privilege('aqua_app_runtime','app.mail_recipient_budget','UPDATE'),has_table_privilege('aqua_app_backup','app.mail_recipient_budget','UPDATE');"
    recipient_expected = sql("aqua_app", recipient_sql)
    sql(
        "aqua_app",
        b"""
BEGIN;
SET LOCAL ROLE aqua_app_runtime;
INSERT INTO app.chats(id,user_id,title,next_message_sequence,message_count) VALUES
 ('10000000-0000-4000-8000-000000000001','00000000-0000-0000-0000-000000000001','Synthetic recovery history',5,4);
INSERT INTO app.messages(id,user_id,chat_id,sequence,role,content,request_id,reply_to,model_id,status) VALUES
 ('20000000-0000-4000-8000-000000000001','00000000-0000-0000-0000-000000000001','10000000-0000-4000-8000-000000000001',1,'user','Completed synthetic input','30000000-0000-4000-8000-000000000001',NULL,'ollama','complete'),
 ('20000000-0000-4000-8000-000000000002','00000000-0000-0000-0000-000000000001','10000000-0000-4000-8000-000000000001',2,'aqua','','30000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','ollama','complete'),
 ('20000000-0000-4000-8000-000000000003','00000000-0000-0000-0000-000000000001','10000000-0000-4000-8000-000000000001',3,'user','Pending synthetic input','30000000-0000-4000-8000-000000000002',NULL,'ollama','complete'),
 ('20000000-0000-4000-8000-000000000004','00000000-0000-0000-0000-000000000001','10000000-0000-4000-8000-000000000001',4,'aqua','','30000000-0000-4000-8000-000000000002','20000000-0000-4000-8000-000000000003','ollama','pending');
INSERT INTO app.analysis_requests(id,user_id,chat_id,client_request_id,fingerprint,input_message_id,reply_message_id,state,reserved_bytes,requested_model,dataset_key,grant_version) VALUES
 ('30000000-0000-4000-8000-000000000001','00000000-0000-0000-0000-000000000001','10000000-0000-4000-8000-000000000001','40000000-0000-4000-8000-000000000001',decode(repeat('ab',32),'hex'),'20000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000002','complete',0,'ollama','synthetic',1),
 ('30000000-0000-4000-8000-000000000002','00000000-0000-0000-0000-000000000001','10000000-0000-4000-8000-000000000001','40000000-0000-4000-8000-000000000002',decode(repeat('cd',32),'hex'),'20000000-0000-4000-8000-000000000003','20000000-0000-4000-8000-000000000004','pending',1024,'ollama','synthetic',1);
INSERT INTO app.visual_results(user_id,chat_id,request_id,response) VALUES
 ('00000000-0000-0000-0000-000000000001','10000000-0000-4000-8000-000000000001','30000000-0000-4000-8000-000000000001','{"status":"success","message":"Completed synthetic answer"}');
INSERT INTO app.workspace_usage(user_id,content_bytes) VALUES('00000000-0000-0000-0000-000000000001',2048);
UPDATE app.workspace_totals SET content_bytes=content_bytes+2048 WHERE singleton;
COMMIT;
""",
    )
    # Schema-5 recovery fences active physical leases without replaying work.
    # These are fixture-only records; their counters are deliberately explicit.
    sql(
        "aqua_app",
        b"""
BEGIN;
SET LOCAL ROLE aqua_app_runtime;
UPDATE app.analysis_requests SET state='running'
 WHERE id='30000000-0000-4000-8000-000000000002';
INSERT INTO app.analysis_jobs(id,user_id,request_id,session_digest,auth_epoch,dataset_key,grant_version,question,model,context,context_digest,content_bytes,state,stage,deadline_at,lease_token,lease_owner,lease_until,physical_until,response) VALUES
 ('30000000-0000-4000-8000-000000000002','00000000-0000-0000-0000-000000000001','30000000-0000-4000-8000-000000000002',decode(repeat('ab',32),'hex'),0,'synthetic',1,'Active synthetic input','ollama','[]',decode(repeat('aa',32),'hex'),64,'running','generating',clock_timestamp()+interval '60 seconds',7,'50000000-0000-4000-8000-000000000001',clock_timestamp()+interval '15 seconds',clock_timestamp()+interval '65 seconds',NULL),
 ('30000000-0000-4000-8000-000000000003','00000000-0000-0000-0000-000000000001',NULL,decode(repeat('ab',32),'hex'),0,'synthetic',1,'Queued synthetic input','ollama','[]',decode(repeat('aa',32),'hex'),64,'queued','queued',clock_timestamp()+interval '60 seconds',0,NULL,NULL,NULL,NULL),
 ('30000000-0000-4000-8000-000000000004','00000000-0000-0000-0000-000000000001',NULL,decode(repeat('ab',32),'hex'),0,'synthetic',1,'','ollama','[]',decode(repeat('aa',32),'hex'),64,'complete','complete',clock_timestamp()+interval '60 seconds',1,NULL,NULL,NULL,'{"status":"success","message":"Legacy synthetic response"}');
INSERT INTO app.analysis_streams(id,user_id,request_id,expires_at,hard_expires_at) VALUES
 ('60000000-0000-4000-8000-000000000001','00000000-0000-0000-0000-000000000001','30000000-0000-4000-8000-000000000002',clock_timestamp()+interval '5 seconds',clock_timestamp()+interval '60 seconds');
UPDATE app.analysis_jobs SET version=3,last_event_sequence=2 WHERE id='30000000-0000-4000-8000-000000000002';
INSERT INTO app.analysis_events(user_id,request_id,sequence,version,state,stage) VALUES
 ('00000000-0000-0000-0000-000000000001','30000000-0000-4000-8000-000000000002',1,2,'queued','queued'),
 ('00000000-0000-0000-0000-000000000001','30000000-0000-4000-8000-000000000002',2,3,'running','generating');
INSERT INTO app.analysis_admission(scope,units,expires_at) VALUES
 ('recovery-fixture-budget',3,clock_timestamp()+interval '1 hour');
UPDATE app.workspace_usage SET content_bytes=content_bytes+192 WHERE user_id='00000000-0000-0000-0000-000000000001';
UPDATE app.workspace_totals SET content_bytes=content_bytes+192 WHERE singleton;
COMMIT;
""",
    )
    admission_sql = b"SELECT scope,units,expires_at FROM app.analysis_admission WHERE scope='recovery-fixture-budget';"
    admission_expected = sql("aqua_app", admission_sql)
    # P09 writes the existing schema-1 preferences table. Restore must preserve
    # choices and revision while the independent session fence revokes access.
    sql(
        "aqua_app",
        b'SET ROLE aqua_app_runtime; INSERT INTO app.user_preferences(user_id,revision,values) VALUES (\'00000000-0000-0000-0000-000000000001\',7,\'{"accent":"sage","sidebar_sections":["prompts","recents"]}\');',
    )
    preferences_sql = b"SELECT schema_version,revision,values FROM app.user_preferences WHERE user_id='00000000-0000-0000-0000-000000000001';"
    preferences_expected = sql("aqua_app", preferences_sql)
    # P10a recovery retains canonical metadata/method tombstones and provenance,
    # while the clone's independent fence invalidates every outstanding proof.
    # These deterministic digests/identities are synthetic and never log in.
    account_target = (
        hashlib.sha256(b'["aqua-account-action-v1","sessions_revoke_all",null]')
        .hexdigest()
        .encode()
    )
    sql(
        "aqua_app",
        b"""
BEGIN;
SET LOCAL ROLE aqua_app_runtime;
UPDATE app.users SET display_name='Synthetic app profile',profile_revision=9,
 picture='https://lh3.googleusercontent.com/synthetic-recovery'
 WHERE id='00000000-0000-0000-0000-000000000001';
INSERT INTO app.user_emails(user_id,address,email_key,verified_at,verification_method,is_primary)
 VALUES('00000000-0000-0000-0000-000000000001','recovery@example.invalid','recovery@example.invalid',now(),'email',true);
INSERT INTO app.password_credentials(user_id,encoded_hash,policy_version)
 VALUES('00000000-0000-0000-0000-000000000001','synthetic-not-an-authentication-hash-0001',1);
INSERT INTO app.external_identities(id,user_id,provider,issuer,subject,is_active,inactive_at,revision,observed_email_key,email_authoritative) VALUES
 ('71000000-0000-4000-8000-000000000001','00000000-0000-0000-0000-000000000001','google','https://accounts.google.com','synthetic-recovery-active',true,NULL,2,'observed@example.invalid',false),
 ('71000000-0000-4000-8000-000000000002','00000000-0000-0000-0000-000000000001','google','https://accounts.google.com','synthetic-recovery-tombstone',false,now(),4,'retired@example.invalid',false);
INSERT INTO app.dataset_grants(user_id,dataset_key,revoked_at,approval_kind,approval_identity_id,approval_evidence)
 VALUES('00000000-0000-0000-0000-000000000001','synthetic-recovery-provenance',now(),'google_subject','71000000-0000-4000-8000-000000000002','synthetic-recovery-tombstone');
INSERT INTO app.auth_challenges(id,user_id,session_id,purpose,secret_digest,binding_digest,account_operation,account_target_digest,account_auth_epoch,created_at,expires_at,consumed_at)
 SELECT '72000000-0000-4000-8000-000000000001',user_id,id,'reauth',decode(repeat('fa',32),'hex'),decode(repeat('fb',32),'hex'),'sessions_revoke_all',decode('TARGET_DIGEST','hex'),0,now(),now()+interval '300 seconds',now()
 FROM app.sessions WHERE token_digest=decode(repeat('ab',32),'hex');
INSERT INTO app.auth_challenges(id,user_id,session_id,purpose,secret_digest,binding_digest,account_operation,account_target_digest,account_auth_epoch,created_at,expires_at)
 SELECT '72000000-0000-4000-8000-000000000002',user_id,id,'reauth',decode(repeat('fd',32),'hex'),decode(repeat('fe',32),'hex'),'sessions_revoke_all',decode('TARGET_DIGEST','hex'),0,now(),now()+interval '300 seconds'
 FROM app.sessions WHERE token_digest=decode(repeat('ab',32),'hex');
INSERT INTO app.account_action_proofs(id,user_id,session_id,challenge_id,secret_digest,auth_epoch,operation,target_digest,method,external_identity_id,created_at,expires_at)
 SELECT '73000000-0000-4000-8000-000000000001',user_id,id,'72000000-0000-4000-8000-000000000001',decode(repeat('fc',32),'hex'),0,'sessions_revoke_all',decode('TARGET_DIGEST','hex'),'google','71000000-0000-4000-8000-000000000001',now(),now()+interval '240 seconds'
 FROM app.sessions WHERE token_digest=decode(repeat('ab',32),'hex');
COMMIT;
""".replace(b"TARGET_DIGEST", account_target),
    )
    account_sql = b"""
SELECT display_name,picture,profile_revision FROM app.users WHERE id='00000000-0000-0000-0000-000000000001';
SELECT address,email_key,verified_at,verification_method,is_primary FROM app.user_emails WHERE user_id='00000000-0000-0000-0000-000000000001' ORDER BY id;
SELECT id,issuer,subject,is_active,inactive_at,revision,observed_email_key,email_authoritative FROM app.external_identities WHERE user_id='00000000-0000-0000-0000-000000000001' ORDER BY id;
SELECT encoded_hash,policy_version,changed_at FROM app.password_credentials WHERE user_id='00000000-0000-0000-0000-000000000001';
SELECT dataset_key,permission,version,granted_at,revoked_at,approval_kind,approval_identity_id,approval_evidence FROM app.dataset_grants WHERE user_id='00000000-0000-0000-0000-000000000001' ORDER BY dataset_key;
SELECT id,user_id,session_id,secret_digest,binding_digest,account_operation,account_target_digest,account_auth_epoch,created_at,expires_at FROM app.auth_challenges WHERE id IN ('72000000-0000-4000-8000-000000000001','72000000-0000-4000-8000-000000000002') ORDER BY id;
SELECT id,user_id,session_id,challenge_id,secret_digest,auth_epoch,operation,target_digest,method,external_identity_id,password_changed_at,created_at,expires_at FROM app.account_action_proofs WHERE id='73000000-0000-4000-8000-000000000001';
SELECT has_table_privilege('aqua_app_runtime','app.account_action_proofs','UPDATE'),has_table_privilege('aqua_app_backup','app.account_action_proofs','UPDATE');
"""
    account_expected = sql("aqua_app", account_sql)
    proof_fence_sql = b"""
SELECT count(*),bool_and(consumed_at IS NOT NULL) FROM app.auth_challenges WHERE id IN ('72000000-0000-4000-8000-000000000001','72000000-0000-4000-8000-000000000002');
SELECT count(*),bool_and(consumed_at IS NOT NULL) FROM app.account_action_proofs WHERE id='73000000-0000-4000-8000-000000000001';
"""
    assert sql("aqua_app", proof_fence_sql).decode().splitlines() == ["2|f", "1|f"]
    dump = docker(
        "exec",
        "-e",
        "PGPASSWORD=fixture-only",
        pg,
        "pg_dump",
        "-h",
        "127.0.0.1",
        "-U",
        "aqua_app_backup",
        "-d",
        "aqua_app",
        "-Fc",
        "--no-owner",
    )
    # Earlier fixture tests may leave synthetic rows. Compare the full counts
    # rather than assuming their order left the database empty.
    count_sql = b"SELECT count(*) FROM app.users; SELECT count(*) FROM app.sessions; SELECT version FROM app.schema_migrations ORDER BY version; SELECT has_table_privilege('aqua_app_runtime','app.users','INSERT'),has_table_privilege('aqua_app_runtime','app.schema_migrations','UPDATE');"
    expected = sql("aqua_app", count_sql).decode().splitlines()
    sql(
        "postgres",
        b"CREATE DATABASE aqua_restore OWNER aqua_app_owner TEMPLATE template0;",
    )
    docker(
        "exec",
        "-i",
        pg,
        "pg_restore",
        "--exit-on-error",
        "--no-owner",
        "--role=aqua_app_owner",
        "-U",
        "postgres",
        "-d",
        "aqua_restore",
        data=dump,
    )
    observed = (
        sql(
            "aqua_restore",
            count_sql,
        )
        .decode()
        .splitlines()
    )
    assert observed == expected and observed[2:] == [
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "t|f",
    ], observed
    assert sql("aqua_restore", account_sql) == account_expected
    assert sql("aqua_restore", proof_fence_sql).decode().splitlines() == ["2|f", "1|f"]
    denied = False
    try:
        sql("aqua_restore", b"SET ROLE aqua_app_backup; DELETE FROM app.users;")
    except RuntimeError:
        denied = True
    assert denied, "restored backup role gained write access"
    sql(
        "aqua_restore",
        (
            Path(__file__).resolve().parents[2] / "ops/appdb/restore_session_fence.sql"
        ).read_bytes(),
    )
    assert sql(
        "aqua_restore",
        b"SELECT count(*) FROM app.sessions WHERE revoked_at IS NULL; SELECT auth_epoch FROM app.users WHERE id='00000000-0000-0000-0000-000000000001';",
    ).decode().splitlines() == ["0", "1"]
    assert sql(
        "aqua_restore",
        b"SELECT count(*) FROM app.password_hash_slots; SELECT count(*) FROM app.account_mail WHERE state IN ('pending','sending'); SELECT state,ciphertext=decode(repeat('00',30),'hex') FROM app.account_mail WHERE id='f4d6b61d-11be-4510-bca3-0521dd724aaa'; SELECT lease_id IS NULL AND lease_expires_at IS NULL FROM app.account_mail_control WHERE singleton;",
    ).decode().splitlines() == ["0", "0", "expired|t", "t"]
    assert sql("aqua_restore", recipient_sql) == recipient_expected
    assert sql("aqua_restore", admission_sql) == admission_expected
    assert sql("aqua_restore", preferences_sql) == preferences_expected
    assert sql("aqua_restore", account_sql) == account_expected
    assert sql("aqua_restore", proof_fence_sql).decode().splitlines() == ["2|t", "1|t"]
    assert sql("aqua_app", proof_fence_sql).decode().splitlines() == ["2|f", "1|f"]
    workspace_sql = b"SELECT state,reserved_bytes FROM app.analysis_requests WHERE user_id='00000000-0000-0000-0000-000000000001' ORDER BY id; SELECT content_bytes FROM app.workspace_usage WHERE user_id='00000000-0000-0000-0000-000000000001'; SELECT count(*) FROM app.visual_results WHERE user_id='00000000-0000-0000-0000-000000000001' AND response->>'message'='Completed synthetic answer'; SELECT status FROM app.messages WHERE id='20000000-0000-4000-8000-000000000004';"
    workspace_expected = ["complete|0", "interrupted|0", "1024", "1", "interrupted"]
    assert (
        sql(
            "aqua_restore",
            b"SELECT t.content_bytes=(SELECT sum(content_bytes) FROM app.workspace_usage) FROM app.workspace_totals t WHERE singleton;",
        )
        .decode()
        .strip()
        == "t"
    )
    assert (
        sql("aqua_restore", workspace_sql).decode().splitlines() == workspace_expected
    )
    lifecycle_sql = b"SELECT state,stage,lease_token,content_bytes,question='',context='[]',response IS NULL,lease_owner IS NULL,lease_until IS NULL,physical_until IS NULL FROM app.analysis_jobs WHERE user_id='00000000-0000-0000-0000-000000000001' ORDER BY id; SELECT count(*) FROM app.analysis_streams WHERE user_id='00000000-0000-0000-0000-000000000001'; SELECT count(*) FROM app.analysis_events WHERE user_id='00000000-0000-0000-0000-000000000001';"
    lifecycle_expected = [
        "interrupted|interrupted|8|0|t|t|t|t|t|t",
        "interrupted|interrupted|1|0|t|t|t|t|t|t",
        "complete|complete|1|0|t|t|t|t|t|t",
        "0",
        "0",
    ]
    assert (
        sql("aqua_restore", lifecycle_sql).decode().splitlines() == lifecycle_expected
    )
    # Recovery fences are repeatable without refunding the reservation twice.
    sql(
        "aqua_restore",
        (
            Path(__file__).resolve().parents[2] / "ops/appdb/restore_session_fence.sql"
        ).read_bytes(),
    )
    assert (
        sql("aqua_restore", workspace_sql).decode().splitlines() == workspace_expected
    )
    assert (
        sql("aqua_restore", lifecycle_sql).decode().splitlines() == lifecycle_expected
    )
    assert sql("aqua_restore", admission_sql) == admission_expected
    assert sql("aqua_restore", account_sql) == account_expected
    assert sql("aqua_restore", proof_fence_sql).decode().splitlines() == ["2|t", "1|t"]
    assert recipient_expected.decode().splitlines()[-1] == "t|f"
    return {
        "status": "passed",
        "dump_bytes": len(dump),
        "dump_sha256": hashlib.sha256(dump).hexdigest(),
        "rows_and_privileges": "preserved",
        "restored_session_fence": "applied",
        "restored_hash_and_mail_fence": "applied",
        "restored_recipient_budget": "preserved_with_runtime_backup_privileges",
        "dump_storage": "memory_only",
        "restored_workspace_history": "preserved_and_pending_fenced",
        "restored_analysis_lifecycle": "interrupted_context_purged_streams_closed",
        "restored_analysis_admission": "preserved",
        "restored_preferences": "values_schema_and_revision_preserved",
        "restored_account_profile_methods": "profile_revision_primary_credentials_and_identity_tombstones_preserved",
        "restored_account_provenance": "derived_grant_identity_binding_and_revocation_preserved",
        "restored_account_action_proofs": "challenge_proof_bindings_preserved_consumption_fenced_repeatably",
    }
