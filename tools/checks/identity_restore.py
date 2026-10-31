"""Schema-7 recovery proof inside the existing disposable synthetic resources."""

import hashlib
import json
from uuid import UUID


def seed(sql, docker, runner):
    targets = {
        name: hashlib.sha256(
            json.dumps(
                ["aqua-account-action-v1", operation, target], separators=(",", ":")
            ).encode()
        )
        .hexdigest()
        .encode()
        for name, operation, target in [
            ("LINK_TARGET", "google_link", None),
            ("EMAIL_TARGET", "email_change", "new-recovery@example.invalid"),
            ("PASSWORD_TARGET", "password_add", "enroll-recovery@example.invalid"),
        ]
    }
    statement = b"""
BEGIN;
SET LOCAL ROLE aqua_app_runtime;
INSERT INTO app.user_notification_settings(user_id,revision,in_app_success,preview)
 VALUES('00000000-0000-0000-0000-000000000001',7,true,'hidden');
INSERT INTO app.users(id,status,display_name,email_revision) VALUES
 ('00000000-0000-0000-0000-000000000003','active','Synthetic enrollment recovery',5);
INSERT INTO app.user_emails(user_id,address,email_key,verified_at,verification_method,is_primary)
 VALUES('00000000-0000-0000-0000-000000000003','enroll-recovery@example.invalid','enroll-recovery@example.invalid',now(),'google',true);
INSERT INTO app.sessions(user_id,token_digest,csrf_digest,auth_epoch,method,idle_expires_at,absolute_expires_at)
 VALUES('00000000-0000-0000-0000-000000000003',decode(repeat('89',32),'hex'),decode(repeat('90',32),'hex'),0,'google',now()+interval '20 minutes',now()+interval '1 hour');
INSERT INTO app.external_identities(id,user_id,provider,issuer,subject,revision,observed_email_key)
 VALUES('71000000-0000-4000-8000-000000000003','00000000-0000-0000-0000-000000000003','google','https://accounts.google.com','synthetic-enrollment-recovery',6,'enroll-recovery@example.invalid');
INSERT INTO app.account_security_requests(id,user_id,session_id,auth_epoch,operation,secret_digest,binding_digest,target_digest,source_email_id,source_email_key,source_email_revision,target_email_key,created_at,expires_at)
 SELECT '74000000-0000-4000-8000-000000000001',u.id,s.id,0,'google_link',decode(repeat('a1',32),'hex'),decode(repeat('a2',32),'hex'),decode('LINK_TARGET','hex'),e.id,e.email_key,u.email_revision,NULL,now(),now()+interval '300 seconds'
 FROM app.users u JOIN app.user_emails e ON e.user_id=u.id AND e.is_primary JOIN app.sessions s ON s.user_id=u.id WHERE s.token_digest=decode(repeat('ab',32),'hex');
UPDATE app.account_security_requests SET claimed_at=now(),verified_at=now(),google_subject='synthetic-pending-new-link',google_email_key='candidate@example.invalid' WHERE id='74000000-0000-4000-8000-000000000001';
INSERT INTO app.account_security_requests(id,user_id,session_id,auth_epoch,operation,secret_digest,binding_digest,target_digest,source_email_id,source_email_key,source_email_revision,target_email_key,created_at,expires_at)
 SELECT '74000000-0000-4000-8000-000000000002',u.id,s.id,0,'email_change',decode(repeat('a3',32),'hex'),decode(repeat('a4',32),'hex'),decode('EMAIL_TARGET','hex'),e.id,e.email_key,u.email_revision,'new-recovery@example.invalid',now(),now()+interval '30 minutes'
 FROM app.users u JOIN app.user_emails e ON e.user_id=u.id AND e.is_primary JOIN app.sessions s ON s.user_id=u.id WHERE s.token_digest=decode(repeat('ab',32),'hex');
INSERT INTO app.account_security_requests(id,user_id,session_id,auth_epoch,operation,secret_digest,binding_digest,target_digest,source_email_id,source_email_key,source_email_revision,target_email_key,source_google_identity_id,source_google_identity_revision,created_at,expires_at)
 SELECT '74000000-0000-4000-8000-000000000003',u.id,s.id,0,'password_add',decode(repeat('a5',32),'hex'),decode(repeat('a6',32),'hex'),decode('PASSWORD_TARGET','hex'),e.id,e.email_key,u.email_revision,e.email_key,'71000000-0000-4000-8000-000000000003',6,now(),now()+interval '30 minutes'
 FROM app.users u JOIN app.user_emails e ON e.user_id=u.id AND e.is_primary JOIN app.sessions s ON s.user_id=u.id WHERE s.token_digest=decode(repeat('89',32),'hex');
INSERT INTO app.auth_challenges(id,user_id,session_id,purpose,secret_digest,target_email_key,password_auth_epoch,account_request_id,expires_at)
 SELECT '82000000-0000-4000-8000-000000000001',user_id,session_id,'email_change_new',sha256(convert_to(repeat('n',43),'UTF8')),target_email_key,auth_epoch,id,expires_at FROM app.account_security_requests WHERE id='74000000-0000-4000-8000-000000000002';
INSERT INTO app.auth_challenges(id,user_id,session_id,purpose,secret_digest,target_email_key,password_auth_epoch,account_request_id,expires_at)
 SELECT '82000000-0000-4000-8000-000000000002',user_id,session_id,'email_change_old',sha256(convert_to(repeat('o',43),'UTF8')),source_email_key,auth_epoch,id,expires_at FROM app.account_security_requests WHERE id='74000000-0000-4000-8000-000000000002';
INSERT INTO app.auth_challenges(id,user_id,session_id,purpose,secret_digest,target_email_key,password_auth_epoch,account_request_id,expires_at)
 SELECT '82000000-0000-4000-8000-000000000003',user_id,session_id,'password_add',sha256(convert_to(repeat('p',43),'UTF8')),source_email_key,auth_epoch,id,expires_at FROM app.account_security_requests WHERE id='74000000-0000-4000-8000-000000000003';
INSERT INTO app.auth_challenges(id,user_id,session_id,purpose,secret_digest,binding_digest,account_operation,account_target_digest,account_auth_epoch,account_google_identity_id,account_google_identity_revision,created_at,expires_at,consumed_at)
 SELECT '82000000-0000-4000-8000-000000000004',user_id,id,'reauth',decode(repeat('a7',32),'hex'),decode(repeat('a8',32),'hex'),'password_add',decode('PASSWORD_TARGET','hex'),0,'71000000-0000-4000-8000-000000000003',6,now(),now()+interval '300 seconds',now() FROM app.sessions WHERE token_digest=decode(repeat('89',32),'hex');
INSERT INTO app.account_action_proofs(id,user_id,session_id,challenge_id,secret_digest,auth_epoch,operation,target_digest,method,external_identity_id,external_identity_revision,created_at,expires_at)
 SELECT '83000000-0000-4000-8000-000000000001',user_id,id,'82000000-0000-4000-8000-000000000004',decode(repeat('a9',32),'hex'),0,'password_add',decode('PASSWORD_TARGET','hex'),'google','71000000-0000-4000-8000-000000000003',6,now(),now()+interval '240 seconds' FROM app.sessions WHERE token_digest=decode(repeat('89',32),'hex');
COMMIT;
"""
    for marker, value in targets.items():
        statement = statement.replace(marker.encode(), value)
    sql("aqua_app", statement)
    # Real encryption/render/open through the candidate code, only fixed fake
    # key/mailboxes and the existing network-none fixture PostgreSQL namespace.
    program = """
import uuid,psycopg
from auth.mailconfig import MailPolicy
from auth.mailoutbox import enqueue,open_job,MailJob
policy=MailPolicy(True,b'R'*32,'https://restore.fixture')
dsn='postgresql://aqua_app_runtime:fixture-only@127.0.0.1:5432/aqua_app?sslmode=disable'
with psycopg.connect(dsn,autocommit=True,connect_timeout=2) as conn:
 with conn.transaction():
  for suffix,purpose,letter,recipient in [(1,'email_change_new','n','new-recovery@example.invalid'),(2,'email_change_old','o','recovery@example.invalid'),(3,'password_add','p','enroll-recovery@example.invalid')]:
   challenge=uuid.UUID('82000000-0000-4000-8000-'+str(suffix).zfill(12))
   expiry=conn.execute('SELECT expires_at FROM app.auth_challenges WHERE id=%s',(challenge,)).fetchone()[0]
   enqueue(conn,recipient=recipient,purpose=purpose,token=letter*43,expires_at=expiry,policy=policy,challenge_id=challenge)
  expiry=conn.execute("SELECT clock_timestamp()+interval '1 hour'").fetchone()[0]
  notice=enqueue(conn,recipient='recovery@example.invalid',purpose='email_changed',token=None,expires_at=expiry,policy=policy)
  row=conn.execute('SELECT id,purpose,recipient_digest,ciphertext,expires_at FROM app.account_mail WHERE id=%s',(notice,)).fetchone()
  assert open_job(MailJob(*row,uuid.uuid4(),0),policy)['template_version']=='aqua-account-v2'
  conn.execute("UPDATE app.account_mail SET state='sending',attempts=1,first_attempt_at=now(),lease_id=%s,lease_expires_at=now()+interval '1 minute' WHERE id=%s",(uuid.uuid4(),notice))
print(str(notice))
"""
    notice_id = (
        docker("exec", "-i", "-w", "/checks/backend", runner, "python", "-c", program)
        .decode()
        .strip()
    )
    assert str(UUID(notice_id)) == notice_id
    retained = b"""
SELECT email_revision FROM app.users WHERE id IN ('00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000003') ORDER BY id;
SELECT user_id,revision,in_app_success,preview FROM app.user_notification_settings ORDER BY user_id;
SELECT id,user_id,session_id,auth_epoch,operation,secret_digest,binding_digest,target_digest,source_email_id,source_email_key,source_email_revision,target_email_key,source_google_identity_id,source_google_identity_revision,google_subject,google_email_key,google_email_authoritative,created_at,expires_at,claimed_at,verified_at FROM app.account_security_requests ORDER BY id;
SELECT id,user_id,session_id,purpose,secret_digest,target_email_key,password_auth_epoch,account_request_id,expires_at FROM app.auth_challenges WHERE account_request_id IS NOT NULL ORDER BY id;
SELECT id,external_identity_id,external_identity_revision,target_digest,auth_epoch,created_at,expires_at FROM app.account_action_proofs WHERE id='83000000-0000-4000-8000-000000000001';
SELECT id,is_active,inactive_at,revision FROM app.external_identities WHERE id='71000000-0000-4000-8000-000000000003';
SELECT purpose,recipient_digest,issued_at,last_queued_at,expires_at FROM app.mail_recipient_budget ORDER BY purpose,recipient_digest;
SELECT has_table_privilege('aqua_app_runtime','app.account_security_requests','UPDATE'),has_table_privilege('aqua_app_backup','app.account_security_requests','UPDATE'),has_table_privilege('aqua_app_runtime','app.user_notification_settings','UPDATE'),has_table_privilege('aqua_app_backup','app.user_notification_settings','UPDATE');
"""
    notice_sql = (
        "SELECT id,purpose,recipient_digest,sha256(ciphertext),expires_at,attempts,first_attempt_at FROM app.account_mail WHERE id='"
        + notice_id
        + "';"
    ).encode()
    fenced = b"""
SELECT count(*),bool_and(consumed_at IS NOT NULL) FROM app.account_security_requests WHERE id IN ('74000000-0000-4000-8000-000000000001','74000000-0000-4000-8000-000000000002','74000000-0000-4000-8000-000000000003');
SELECT count(*),bool_and(consumed_at IS NOT NULL) FROM app.auth_challenges WHERE account_request_id IN ('74000000-0000-4000-8000-000000000001','74000000-0000-4000-8000-000000000002','74000000-0000-4000-8000-000000000003');
SELECT consumed_at IS NOT NULL FROM app.account_action_proofs WHERE id='83000000-0000-4000-8000-000000000001';
SELECT count(*) FROM app.account_mail WHERE challenge_id IN ('82000000-0000-4000-8000-000000000001','82000000-0000-4000-8000-000000000002','82000000-0000-4000-8000-000000000003') AND state IN ('pending','sending');
"""
    return {
        "retained_sql": retained,
        "retained": sql("aqua_app", retained),
        "notice_sql": notice_sql,
        "notice": sql("aqua_app", notice_sql),
        "fenced_sql": fenced,
        "notice_id": notice_id,
    }


def verify(sql, database, evidence, *, fenced):
    assert sql(database, evidence["retained_sql"]) == evidence["retained"]
    assert sql(database, evidence["notice_sql"]) == evidence["notice"]
    assert sql(database, evidence["fenced_sql"]).decode().splitlines() == (
        ["3|t", "3|t", "t", "0"] if fenced else ["3|f", "3|f", "f", "3"]
    )
    status = (
        "SELECT state,lease_id IS NULL AND lease_expires_at IS NULL FROM app.account_mail WHERE id='"
        + evidence["notice_id"]
        + "';"
    ).encode()
    assert sql(database, status).decode().strip() == (
        "pending|t" if fenced else "sending|f"
    )
