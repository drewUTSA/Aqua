"""Purge only a sealed original generation, one bounded database step at a time."""

from analysis import lifecycle, records as analysis_records
from analysis.policy import TERMINAL
from auth.mailqueue import SEND_LOCK
from retirement.intents import MAX_EPOCH
from privacy import records as exports
from privacy.download import PHYSICAL
from workspace.database import allocate, one


def _refund(conn, owner, amount):
    if amount:
        allocate(conn, owner, -amount)


def _downloads(owner):
    with PHYSICAL.lock:
        return PHYSICAL.poisoned or owner in PHYSICAL.holders.values()


def _exports(conn, owner, floor, closed):
    row = one(
        conn,
        "SELECT * FROM app.data_exports WHERE user_id=%s AND (%s OR privacy_epoch<%s) ORDER BY created_at,id LIMIT 1 FOR UPDATE",
        (owner, closed, floor),
    )
    if row is None:
        return False
    row = exports.expire(conn, row)
    if exports.cleanup(conn, row):
        conn.execute(
            "DELETE FROM app.data_exports WHERE user_id=%s AND id=%s",
            (owner, row["id"]),
        )
    return True


def _analysis(conn, owner, floor):
    row = one(
        conn,
        "SELECT * FROM app.analysis_jobs WHERE user_id=%s AND history_generation<%s AND (NOT(state=ANY(%s)) OR content_bytes>0 OR physical_until IS NULL) ORDER BY created_at,id LIMIT 1 FOR UPDATE",
        (owner, floor, list(TERMINAL)),
    )
    if row is None:
        return False
    if row["state"] not in TERMINAL:
        lifecycle.terminate(conn, row, "interrupted")
        return True
    if row["content_bytes"]:
        analysis_records.purge_input(conn, row)
        return True
    if row["physical_until"] is not None:
        return False  # Only the real supervisor/recovery may acknowledge exit.
    for table, column in (("analysis_streams", "id"), ("analysis_events", "sequence")):
        removed = conn.execute(
            f"DELETE FROM app.{table} WHERE user_id=%s AND request_id=%s AND {column} IN (SELECT {column} FROM app.{table} WHERE user_id=%s AND request_id=%s ORDER BY {column} LIMIT 32) RETURNING {column}",
            (owner, row["id"], owner, row["id"]),
        ).fetchall()
        if removed:
            return True
    conn.execute(
        "DELETE FROM app.analysis_jobs WHERE user_id=%s AND id=%s", (owner, row["id"])
    )
    return True


def _history(conn, owner, floor):
    removed = conn.execute(
        "DELETE FROM app.visual_results WHERE user_id=%s AND id IN (SELECT v.id FROM app.visual_results v JOIN app.chats c ON c.user_id=v.user_id AND c.id=v.chat_id WHERE v.user_id=%s AND c.history_generation<%s ORDER BY v.id LIMIT 16) RETURNING octet_length(response::text)",
        (owner, owner, floor),
    ).fetchall()
    if removed:
        _refund(conn, owner, sum(row[0] for row in removed))
        return True
    requests = conn.execute(
        "SELECT r.id FROM app.analysis_requests r JOIN app.chats c ON c.user_id=r.user_id AND c.id=r.chat_id WHERE r.user_id=%s AND c.history_generation<%s AND NOT EXISTS(SELECT 1 FROM app.analysis_jobs j WHERE j.user_id=r.user_id AND j.request_id=r.id) AND NOT EXISTS(SELECT 1 FROM app.analysis_requests x WHERE x.user_id=r.user_id AND x.chat_id=r.chat_id AND x.retry_of=r.id) ORDER BY r.id LIMIT 32 FOR UPDATE OF r",
        (owner, floor),
    ).fetchall()
    if requests:
        identifiers = [row[0] for row in requests]
        conn.execute(
            "UPDATE app.messages SET request_id=NULL WHERE user_id=%s AND request_id=ANY(%s)",
            (owner, identifiers),
        )
        removed = conn.execute(
            "DELETE FROM app.analysis_requests WHERE user_id=%s AND id=ANY(%s) RETURNING reserved_bytes",
            (owner, identifiers),
        ).fetchall()
        _refund(conn, owner, sum(row[0] for row in removed))
        return True
    removed = conn.execute(
        "DELETE FROM app.messages WHERE user_id=%s AND (chat_id,id) IN (SELECT m.chat_id,m.id FROM app.messages m JOIN app.chats c ON c.user_id=m.user_id AND c.id=m.chat_id WHERE m.user_id=%s AND c.history_generation<%s AND NOT EXISTS(SELECT 1 FROM app.analysis_requests r WHERE r.user_id=m.user_id AND r.chat_id=m.chat_id AND (r.input_message_id=m.id OR r.reply_message_id=m.id)) AND NOT EXISTS(SELECT 1 FROM app.messages x WHERE x.user_id=m.user_id AND x.chat_id=m.chat_id AND x.reply_to=m.id) ORDER BY m.chat_id,m.id LIMIT 32) RETURNING octet_length(content)",
        (owner, owner, floor),
    ).fetchall()
    if removed:
        _refund(conn, owner, sum(row[0] for row in removed))
        return True
    removed = conn.execute(
        "DELETE FROM app.chats WHERE user_id=%s AND id IN (SELECT c.id FROM app.chats c WHERE c.user_id=%s AND c.history_generation<%s AND NOT EXISTS(SELECT 1 FROM app.messages m WHERE m.user_id=c.user_id AND m.chat_id=c.id) AND NOT EXISTS(SELECT 1 FROM app.analysis_requests r WHERE r.user_id=c.user_id AND r.chat_id=c.id) ORDER BY c.id LIMIT 1) RETURNING CASE WHEN deleted_at IS NULL THEN octet_length(title) ELSE 0 END",
        (owner, owner, floor),
    ).fetchall()
    if removed:
        _refund(conn, owner, sum(row[0] for row in removed))
        return True
    return False


def _mail_values(job):
    raw = bytes(job["mail_recipients"])
    return (
        str(job["user_id"]),
        [raw[offset : offset + 32] for offset in range(0, len(raw), 32)],
        job["created_at"],
    )


MAIL = "(m.challenge_id IN (SELECT id FROM app.auth_challenges WHERE user_id=%s) OR (m.recipient_digest=ANY(%s) AND m.created_at<=%s))"


def _sending(conn, job):
    return (
        conn.execute(
            "SELECT 1 FROM app.account_mail m WHERE "
            + MAIL
            + " AND m.state='sending' LIMIT 1",
            _mail_values(job),
        ).fetchone()
        is not None
    )


def _account(conn, owner, job):
    # A sender that has already read a private envelope owns its real lifetime.
    # Do not expire its lease or remove its evidence to pretend delivery stopped.
    if conn.execute(
        "SELECT pg_try_advisory_xact_lock(%s,%s)", (SEND_LOCK, 0)
    ).fetchone() != (True,) or _sending(conn, job):
        return False
    removed = conn.execute(
        "DELETE FROM app.account_mail WHERE state<>'sending' AND id IN (SELECT m.id FROM app.account_mail m WHERE "
        + MAIL
        + " AND m.state<>'sending' ORDER BY m.id LIMIT 32 FOR UPDATE OF m SKIP LOCKED) RETURNING id",
        _mail_values(job),
    ).fetchall()
    if removed:
        return True
    for table, key in (
        ("saved_prompt_uses", "client_request_id"),
        ("account_action_proofs", "id"),
    ):
        removed = conn.execute(
            f"DELETE FROM app.{table} WHERE user_id=%s AND {key} IN (SELECT {key} FROM app.{table} WHERE user_id=%s ORDER BY {key} LIMIT 32) RETURNING {key}",
            (owner, owner),
        ).fetchall()
        if removed:
            return True
    removed = conn.execute(
        "DELETE FROM app.auth_challenges WHERE id IN (SELECT c.id FROM app.auth_challenges c WHERE (c.user_id=%s OR (c.user_id IS NULL AND c.target_email_key IN (SELECT email_key FROM app.user_emails WHERE user_id=%s))) AND NOT EXISTS(SELECT 1 FROM app.account_mail m WHERE m.challenge_id=c.id) ORDER BY c.id LIMIT 32) RETURNING id",
        (owner, owner),
    ).fetchall()
    if removed:
        return True
    for table, size in (
        ("account_security_requests", "0"),
        ("dataset_grants", "0"),
        ("sessions", "0"),
        (
            "saved_prompts",
            "CASE WHEN deleted_at IS NULL THEN octet_length(label)+octet_length(prompt) ELSE 0 END",
        ),
        ("projects", "CASE WHEN deleted_at IS NULL THEN octet_length(name) ELSE 0 END"),
        ("password_credentials", "0"),
        ("user_notification_settings", "0"),
        ("user_preferences", "0"),
        ("workspace_admission", "0"),
        ("user_emails", "0"),
        ("external_identities", "0"),
    ):
        # Fixed reviewed identifiers; no request-selected table/SQL exists.
        key = (
            "user_id"
            if table
            in {
                "password_credentials",
                "user_notification_settings",
                "user_preferences",
                "workspace_admission",
                "dataset_grants",
            }
            else "id"
        )
        # Dataset grants have one row per dataset, not a single row per owner.
        if table == "dataset_grants":
            key = "dataset_key"
        unused = (
            " AND NOT EXISTS(SELECT 1 FROM app.auth_challenges c WHERE c.account_request_id=app.account_security_requests.id)"
            if table == "account_security_requests"
            else ""
        )
        removed = conn.execute(
            f"DELETE FROM app.{table} WHERE user_id=%s AND {key} IN (SELECT {key} FROM app.{table} WHERE user_id=%s{unused} ORDER BY {key} LIMIT 32) RETURNING {size}",
            (owner, owner),
        ).fetchall()
        if removed:
            _refund(conn, owner, sum(row[0] for row in removed))
            return True
    usage = conn.execute(
        "SELECT content_bytes FROM app.workspace_usage WHERE user_id=%s", (owner,)
    ).fetchone()
    if usage:
        _refund(conn, owner, usage[0])
        conn.execute("DELETE FROM app.workspace_usage WHERE user_id=%s", (owner,))
        return True
    return bool(
        conn.execute(
            "DELETE FROM app.users WHERE id=%s AND status='deleting' RETURNING id",
            (owner,),
        ).fetchone()
    )


def step(conn, job):
    """Caller verified ConfirmedRetirement and holds global -> user -> job locks."""
    owner, floor, closed = (
        str(job["user_id"]),
        job["history_floor"],
        job["account_closed"],
    )
    if closed:
        # Closing an account retires every valid generation. Recovery may find
        # a newer local floor, which must not escape bounded cleanup and fall
        # through to an unbounded user-FK cascade.
        floor = MAX_EPOCH + 1
    if (
        _exports(conn, owner, job["privacy_floor"], closed)
        or _analysis(conn, owner, floor)
        or _history(conn, owner, floor)
    ):
        return "progress"
    if (
        conn.execute(
            "SELECT 1 FROM app.analysis_jobs WHERE user_id=%s AND history_generation<%s LIMIT 1",
            (owner, floor),
        ).fetchone()
        or conn.execute(
            "SELECT 1 FROM app.chats WHERE user_id=%s AND history_generation<%s LIMIT 1",
            (owner, floor),
        ).fetchone()
        or _downloads(owner)
    ):
        return "waiting"
    if closed:
        if _account(conn, owner, job):
            return "progress"
        if (
            _sending(conn, job)
            or conn.execute("SELECT 1 FROM app.users WHERE id=%s", (owner,)).fetchone()
        ):
            return "waiting"
    return "complete"
