"""Actual restored app SQL; the independent authority is explicitly synthetic."""

from contextlib import nullcontext

import pytest

from retirement.recovery import reconcile
from test_deletion_lifecycle import deletion as _deletion_fixture
from test_retirement_recovery import restored
from workspace.database import allocate

deletion = _deletion_fixture


@pytest.mark.parametrize("scope", ["chat_history_v1", "account_v1"])
def test_restored_notes_obey_original_account_floor_but_remain_a_separate_library(
    deletion, app_database, scope
):
    _, service, owner, recovery, protected = restored(deletion, app_database, scope)
    # Model restored library rows from two old scopes; no user/session/source
    # authority is invented, and the existing recovery protocol is unchanged.
    with service.storage.transaction() as conn:
        allocate(conn, owner, 40)
        conn.execute(
            "INSERT INTO app.context_notes(user_id,dataset_key,grant_version,kind,label,body,"
            "client_request_id,fingerprint,content_bytes,created_at,updated_at) VALUES"
            "(%s,%s,1,'note','Restored','User context',gen_random_uuid(),%s,20,'2020-01-01T00:00:00Z','2020-01-01T00:00:00Z'),"
            "(%s,%s,7,'metric_definition','Restored','User context',gen_random_uuid(),%s,20,'2020-01-01T00:00:00Z','2020-01-01T00:00:00Z')",
            (owner, "a" * 64, bytes(32), owner, "b" * 64, bytes(32)),
        )
    result = reconcile(
        service.storage,
        recovery,
        protected,
        purge_guard=lambda closed: nullcontext(True),
    )
    assert result.ready is True and result.events_verified == 1
    with service.storage.transaction() as conn:
        count = conn.execute(
            "SELECT count(*),COALESCE(sum(content_bytes),0) FROM app.context_notes WHERE user_id=%s",
            (owner,),
        ).fetchone()
        if scope == "account_v1":
            assert count == (0, 0)
            assert (
                conn.execute(
                    "SELECT id FROM app.users WHERE id=%s", (owner,)
                ).fetchone()
                is None
            )
        else:
            assert count == (2, 40)
            assert conn.execute(
                "SELECT content_bytes FROM app.workspace_usage WHERE user_id=%s",
                (owner,),
            ).fetchone() == (40,)
