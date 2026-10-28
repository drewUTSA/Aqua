"""Real older private schemas migrate/recover without replaying unfinished work."""

from pathlib import Path

import pytest

from storage.migrate import apply, migrations


@pytest.mark.parametrize("version", [3, 4])
def test_recovery_fence_remains_compatible_with_older_encrypted_snapshots(
    app_database, version
):
    assert apply(app_database, migrations()[:version]) == version
    fence = Path(__file__).resolve().parents[2] / "ops/appdb/restore_session_fence.sql"
    app_database.execute(fence.read_text())
    app_database.execute("RESET ROLE")
    assert apply(app_database) == 6


def test_schema4_pending_reservation_is_interrupted_and_refunded_only_once(
    app_database,
):
    assert apply(app_database, migrations()[:4]) == 4
    with app_database.transaction():
        app_database.execute("SET LOCAL ROLE aqua_app_owner")
        app_database.execute("""
INSERT INTO app.users(id,status,display_name) VALUES
 ('00000000-0000-4000-8000-000000000001','active','Synthetic upgrade');
INSERT INTO app.chats(id,user_id,title,next_message_sequence,message_count) VALUES
 ('10000000-0000-4000-8000-000000000001','00000000-0000-4000-8000-000000000001','Synthetic unfinished conversation',3,2);
INSERT INTO app.messages(id,user_id,chat_id,sequence,role,content,request_id,reply_to,model_id,status) VALUES
 ('20000000-0000-4000-8000-000000000001','00000000-0000-4000-8000-000000000001','10000000-0000-4000-8000-000000000001',1,'user','Unfinished synthetic input','30000000-0000-4000-8000-000000000001',NULL,'ollama','complete'),
 ('20000000-0000-4000-8000-000000000002','00000000-0000-4000-8000-000000000001','10000000-0000-4000-8000-000000000001',2,'aqua','','30000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','ollama','pending');
INSERT INTO app.analysis_requests(id,user_id,chat_id,client_request_id,fingerprint,input_message_id,reply_message_id,state,reserved_bytes,requested_model,dataset_key,grant_version) VALUES
 ('30000000-0000-4000-8000-000000000001','00000000-0000-4000-8000-000000000001','10000000-0000-4000-8000-000000000001','40000000-0000-4000-8000-000000000001',decode(repeat('ab',32),'hex'),'20000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000002','pending',1024,'ollama','synthetic',1);
INSERT INTO app.workspace_usage(user_id,content_bytes) VALUES
 ('00000000-0000-4000-8000-000000000001',1050);
UPDATE app.workspace_totals SET content_bytes=1050 WHERE singleton;
""")
    assert apply(app_database) == 6

    def observed():
        app_database.execute("SET ROLE aqua_app_owner")
        state = app_database.execute("""
SELECT r.state,r.reserved_bytes,m.status,u.content_bytes,t.content_bytes
FROM app.analysis_requests r
JOIN app.messages m ON m.id=r.reply_message_id
JOIN app.workspace_usage u ON u.user_id=r.user_id
CROSS JOIN app.workspace_totals t WHERE t.singleton;
""").fetchone()
        assert app_database.execute(
            "SELECT count(*) FROM app.analysis_jobs"
        ).fetchone() == (0,)
        app_database.execute("RESET ROLE")
        return state

    assert observed() == ("interrupted", 0, "interrupted", 26, 26)
    assert apply(app_database) == 6
    assert observed() == ("interrupted", 0, "interrupted", 26, 26)
