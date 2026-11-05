"""Download budgets are durable, bounded and independent of stream slot locks."""

import hashlib

from workspace.errors import WorkspaceError
from privacy import policy
from privacy.database import global_lock


def download(conn, owner):
    # Separate committed admission: failed/foreign IDs do not refund a counter.
    global_lock(conn)
    instant = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    conn.execute(
        "DELETE FROM app.privacy_admission WHERE (scope,key_digest) IN (SELECT scope,key_digest FROM app.privacy_admission WHERE expires_at<=%s ORDER BY expires_at,scope,key_digest LIMIT 64)",
        (instant,),
    )
    count = conn.execute("SELECT count(*) FROM app.privacy_admission").fetchone()[0]
    updates = []
    for scope, value, maximum in [
        ("download:global", "all", policy.DOWNLOAD_GLOBAL_PER_MINUTE),
        ("download:account", owner, policy.DOWNLOAD_ACCOUNT_PER_MINUTE),
    ]:
        key = hashlib.sha256(value.encode()).digest()
        row = conn.execute(
            "SELECT hits,expires_at FROM app.privacy_admission WHERE scope=%s AND key_digest=%s",
            (scope, key),
        ).fetchone()
        if row is None:
            count += 1
        if count > 2048 or row and row[1] > instant and row[0] >= maximum:
            raise WorkspaceError("rate_limited", 429)
        updates.append((scope, key))
    for scope, key in updates:
        conn.execute(
            "INSERT INTO app.privacy_admission(scope,key_digest,hits,expires_at) VALUES(%s,%s,1,%s+interval '1 minute') ON CONFLICT(scope,key_digest) DO UPDATE SET hits=CASE WHEN app.privacy_admission.expires_at<=%s THEN 1 ELSE app.privacy_admission.hits+1 END,expires_at=CASE WHEN app.privacy_admission.expires_at<=%s THEN EXCLUDED.expires_at ELSE app.privacy_admission.expires_at END",
            (scope, key, instant, instant, instant),
        )
