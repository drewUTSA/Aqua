"""Success and failure settle under the same final authority/time/lease fence."""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.service import Analysis
import logging
from workspace.errors import WorkspaceError
from analysis import lifecycle, records
from analysis.policy import TERMINAL

log = logging.getLogger("aqua.analysis")


def settle(
    service: Analysis,
    job: dict,
    state: str | None,
    reaped: bool,
    release_slot: bool,
    quarantine: bool,
    response: dict | None,
    status: int,
) -> None:
    with service.storage.transaction() as conn:
        conn.execute(
            "SELECT id FROM app.users WHERE id=%s FOR UPDATE", (job["user_id"],)
        )
        current = records.get(conn, str(job["user_id"]), str(job["id"]), lock=True)
        # An old worker's exception/reap is just as fenced as its success.
        # Never cancel or free a newer lease after an earlier check failed.
        if (
            current["lease_token"] != job["lease_token"]
            or current["lease_owner"] != job["lease_owner"]
        ):
            if (
                current["state"] in TERMINAL
                and current["lease_owner"] == job["lease_owner"]
                and current["lease_token"] == job["lease_token"] + 1
            ):
                expression = (
                    "NULL"
                    if release_slot
                    else (
                        "'9999-01-01T00:00:00Z'::timestamptz"
                        if quarantine
                        else "greatest(physical_until,clock_timestamp()+interval '10 seconds')"
                    )
                )
                conn.execute(
                    f"UPDATE app.analysis_jobs SET physical_until={expression} WHERE id=%s AND lease_owner=%s AND lease_token=%s AND state=ANY(%s)",
                    (
                        job["id"],
                        job["lease_owner"],
                        current["lease_token"],
                        list(TERMINAL),
                    ),
                )
            return
        if (
            state == "interrupted"
            and conn.execute(
                "SELECT %s<=clock_timestamp()", (current["deadline_at"],)
            ).fetchone()[0]
        ):
            state = "expired"
        if state is None:
            try:
                session = records.authorize(
                    conn, records.identity(current), service.policy, current
                )
                instant = conn.execute("SELECT clock_timestamp()").fetchone()[0]
                if instant >= current["deadline_at"]:
                    state = "expired"
                elif (
                    current["lease_until"] is None or instant >= current["lease_until"]
                ):
                    state = "interrupted"
                elif current["state"] != "running" or current["cancel_requested"]:
                    state = (
                        "cancelled" if current["cancel_requested"] else "interrupted"
                    )
                else:
                    try:
                        # A late final CAS rolls back the entire result and
                        # byte-accounting savepoint, then records expiry.
                        with conn.transaction():
                            lifecycle.complete(conn, current, session, response, status)
                    except lifecycle.CommitFence as error:
                        state = error.state
            except WorkspaceError:
                state = "interrupted"
        if state is not None:
            lifecycle.terminate(
                conn,
                current,
                state,
                reaped=release_slot,
                quarantine=quarantine,
                remote_uncertain=reaped and not release_slot,
            )
    log.info(
        "analysis_terminal request_id=%s outcome=%s child_reaped=%s remote_quiesced=%s",
        str(job["id"]),
        state or ("complete" if response["status"] == "success" else "error"),
        reaped,
        release_slot,
    )
