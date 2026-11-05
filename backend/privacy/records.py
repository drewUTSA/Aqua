"""Private export rows/chunks use closed queries and exact owner predicates."""

from workspace.database import one
from workspace.errors import WorkspaceError
from privacy import policy


def get(conn, owner, job_id, *, lock=False):
    row = one(
        conn,
        "SELECT * FROM app.data_exports WHERE user_id=%s AND id=%s"
        + (" FOR UPDATE" if lock else ""),
        (owner, job_id),
    )
    if row is None:
        raise WorkspaceError("not_found")
    return row


def expire(conn, row, *, failure=None):
    result = one(
        conn,
        "UPDATE app.data_exports SET state=%s,error_code=%s,sha256=NULL,lease_owner=NULL,lease_until=NULL WHERE user_id=%s AND id=%s RETURNING *",
        ("failed" if failure else "expired", failure, row["user_id"], row["id"]),
    )
    conn.execute(
        "UPDATE app.privacy_control SET worker_owner=NULL,worker_until=NULL,worker_job=NULL WHERE singleton AND worker_job=%s",
        (row["id"],),
    )
    return result


def cleanup(conn, row):
    """Caller holds privacy-global -> user -> job. Never release undeleted bytes."""
    removed = conn.execute(
        "DELETE FROM app.data_export_chunks WHERE (job_id,generation,ordinal) IN (SELECT job_id,generation,ordinal FROM app.data_export_chunks WHERE user_id=%s AND job_id=%s ORDER BY generation,ordinal LIMIT %s FOR UPDATE SKIP LOCKED) RETURNING octet_length(body)",
        (row["user_id"], row["id"], policy.CLEANUP_CHUNKS),
    ).fetchall()
    amount = sum(item[0] for item in removed)
    if row["reserved_bytes"] == 0 and amount:
        conn.execute(
            "UPDATE app.privacy_control SET stored_bytes=stored_bytes-%s WHERE singleton",
            (amount,),
        )
    remaining, size = conn.execute(
        "SELECT count(*),COALESCE(sum(octet_length(body)),0) FROM app.data_export_chunks WHERE user_id=%s AND job_id=%s",
        (row["user_id"], row["id"]),
    ).fetchone()
    reserved = row["reserved_bytes"]
    if remaining == 0 and reserved:
        conn.execute(
            "UPDATE app.privacy_control SET reserved_bytes=reserved_bytes-%s WHERE singleton",
            (reserved,),
        )
        reserved = 0
    row = one(
        conn,
        "UPDATE app.data_exports SET reserved_bytes=%s,output_bytes=%s,chunk_count=%s WHERE user_id=%s AND id=%s RETURNING *",
        (reserved, size, remaining, row["user_id"], row["id"]),
    )
    if (
        remaining == 0
        and row["expires_at"] <= conn.execute("SELECT clock_timestamp()").fetchone()[0]
    ):
        conn.execute(
            "DELETE FROM app.data_exports WHERE user_id=%s AND id=%s",
            (row["user_id"], row["id"]),
        )
    return remaining == 0


def lease_current(conn, row, actor, generation):
    return (
        conn.execute(
            "SELECT 1 FROM app.data_exports WHERE user_id=%s AND id=%s AND state='working' AND lease_owner=%s AND generation=%s AND lease_until>clock_timestamp() AND deadline_at>clock_timestamp() AND expires_at>clock_timestamp()",
            (row["user_id"], row["id"], actor, generation),
        ).fetchone()
        is not None
    )
