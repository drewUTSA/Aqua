"""Synthetic ready/partial-output invalidation in the real restored clone."""

BODY = b'{"synthetic_export_canary":"PRIVATE_EXPORT_RECOVERY"}'
OWNERS = (
    "95000000-0000-4000-8000-000000000001",
    "95000000-0000-4000-8000-000000000002",
)
JOBS = ("97000000-0000-4000-8000-000000000001", "97000000-0000-4000-8000-000000000002")


def seed(sql):
    # Fixed fixture identities only; no production/custom input is executable.
    statement = b"""
BEGIN;
SET LOCAL ROLE aqua_app_runtime;
INSERT INTO app.users(id,status,display_name) VALUES
 ('95000000-0000-4000-8000-000000000001','active','Synthetic ready export'),
 ('95000000-0000-4000-8000-000000000002','active','Synthetic partial export');
INSERT INTO app.sessions(id,user_id,token_digest,csrf_digest,auth_epoch,method,idle_expires_at,absolute_expires_at) VALUES
 ('96000000-0000-4000-8000-000000000001','95000000-0000-4000-8000-000000000001',decode(repeat('d1',32),'hex'),decode(repeat('d2',32),'hex'),0,'google',now()+interval '10 minutes',now()+interval '1 hour'),
 ('96000000-0000-4000-8000-000000000002','95000000-0000-4000-8000-000000000002',decode(repeat('d3',32),'hex'),decode(repeat('d4',32),'hex'),0,'google',now()+interval '10 minutes',now()+interval '1 hour');
INSERT INTO app.data_exports(id,user_id,session_id,intent_id,scope,auth_epoch,privacy_epoch,state,created_at,expires_at,deadline_at,reserved_bytes,output_bytes,chunk_count,sha256,generation,attempts,lease_owner,lease_until) VALUES
 ('97000000-0000-4000-8000-000000000001','95000000-0000-4000-8000-000000000001','96000000-0000-4000-8000-000000000001','98000000-0000-4000-8000-000000000001','personal_v1',0,1,'ready',now(),now()+interval '1 hour',now()+interval '120 seconds',0,octet_length(decode('BODY','hex')),1,encode(sha256(decode('BODY','hex')),'hex'),1,1,NULL,NULL),
 ('97000000-0000-4000-8000-000000000002','95000000-0000-4000-8000-000000000002','96000000-0000-4000-8000-000000000002','98000000-0000-4000-8000-000000000002','personal_v1',0,1,'working',now(),now()+interval '1 hour',now()+interval '120 seconds',33554432,octet_length(decode('BODY','hex')),1,NULL,1,1,'99000000-0000-4000-8000-000000000001',now()+interval '15 seconds');
INSERT INTO app.data_export_chunks(user_id,job_id,generation,ordinal,body,digest) SELECT user_id,id,1,0,decode('BODY','hex'),sha256(decode('BODY','hex')) FROM app.data_exports WHERE id IN ('97000000-0000-4000-8000-000000000001','97000000-0000-4000-8000-000000000002');
UPDATE app.privacy_control SET reserved_bytes=reserved_bytes+33554432,stored_bytes=stored_bytes+octet_length(decode('BODY','hex')),worker_owner='99000000-0000-4000-8000-000000000001',worker_job='97000000-0000-4000-8000-000000000002',worker_until=now()+interval '15 seconds' WHERE singleton;
INSERT INTO app.privacy_admission(scope,key_digest,hits,expires_at) VALUES
 ('download:global',decode(repeat('ef',32),'hex'),10,now()+interval '1 minute'),
 ('download:account',decode(repeat('ed',32),'hex'),5,now()+interval '1 minute');
COMMIT;
""".replace(b"BODY", BODY.hex().encode())
    sql("aqua_app", statement)
    return {
        "outputs": sql("aqua_app", outputs()),
        "admission": sql("aqua_app", admission()),
    }


def outputs():
    return b"SELECT id,state,reserved_bytes,output_bytes,chunk_count,sha256,generation,attempts,lease_owner,lease_until FROM app.data_exports WHERE id IN ('97000000-0000-4000-8000-000000000001','97000000-0000-4000-8000-000000000002') ORDER BY id; SELECT job_id,generation,ordinal,encode(body,'hex'),encode(digest,'hex') FROM app.data_export_chunks WHERE job_id IN ('97000000-0000-4000-8000-000000000001','97000000-0000-4000-8000-000000000002') ORDER BY job_id,generation,ordinal;"


def admission():
    return b"SELECT scope,encode(key_digest,'hex'),hits,expires_at FROM app.privacy_admission WHERE key_digest IN(decode(repeat('ef',32),'hex'),decode(repeat('ed',32),'hex')) ORDER BY scope,key_digest;"


def verify(sql, database, expected, *, fenced):
    assert sql(database, admission()) == expected["admission"]
    if not fenced:
        assert sql(database, outputs()) == expected["outputs"]
        return
    assert (
        sql(
            database,
            b"SELECT state,reserved_bytes,output_bytes,chunk_count,sha256 IS NULL,lease_owner IS NULL,lease_until IS NULL,generation,attempts FROM app.data_exports WHERE id IN('97000000-0000-4000-8000-000000000001','97000000-0000-4000-8000-000000000002') ORDER BY id;",
        )
        .decode()
        .splitlines()
        == ["expired|0|0|0|t|t|t|1|1"] * 2
    )
    assert sql(
        database,
        b"SELECT count(*) FROM app.data_export_chunks; SELECT reserved_bytes,stored_bytes,worker_owner IS NULL,worker_job IS NULL,worker_until IS NULL FROM app.privacy_control WHERE singleton;",
    ).decode().splitlines() == ["0", "0|0|t|t|t"]
    assert (
        sql(
            database,
            b"SELECT min(privacy_epoch)>1 FROM app.users WHERE id IN('95000000-0000-4000-8000-000000000001','95000000-0000-4000-8000-000000000002');",
        ).strip()
        == b"t"
    )
