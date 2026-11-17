"""Fresh saved-job authorization surrounds a provider-free bounded projection."""

from collections.abc import Callable
import time

from analysis import records
from auth.security import UserSession
from companion.policy import CompanionPolicy
from result_companion.facts import build, encoded, require
from workspace.errors import WorkspaceError
from workspace.service import Workspace


class ResultCompanion:
    def __init__(
        self,
        workspace: Workspace,
        policy: CompanionPolicy,
        *,
        clock: Callable[[], float] = time.perf_counter,
    ):
        self.workspace, self.policy, self.clock = workspace, policy, clock

    def read(self, session: UserSession, *, request_id: str, column_index: int) -> dict:
        if type(self.policy) is not CompanionPolicy or not self.policy.enabled:
            raise WorkspaceError("not_found", 404)
        deadline = self.clock() + 2

        def check():
            if self.clock() >= deadline:
                raise WorkspaceError("service_unavailable", 503)

        check()
        self.workspace.reserve(session)
        check()
        with self.workspace.storage.transaction() as conn:
            job = records.get(conn, session.user["id"], request_id)
            if not job["request_id"] or str(job["request_id"]) != request_id:
                raise WorkspaceError("not_found", 404)
            current = records.authorize(conn, session, self.workspace.policy, job)
            check()
            if job["state"] != "complete":
                raise WorkspaceError("not_found", 404)
            saved = records.snapshot(conn, current, request_id)
            reply = saved["assistant_message"]
            if (
                saved["request"]["state"] != "complete"
                or reply["response"] is None
                or reply["response"].get("status") != "success"
            ):
                raise WorkspaceError("not_found", 404)
            require(
                str(saved["request"]["id"]) == request_id
                and str(reply["request_id"]) == request_id
            )
            require(
                str(reply["chat_id"]) == str(saved["chat"]["id"])
                and str(reply["id"]) == str(saved["request"]["reply_message_id"])
            )
            require(type(job["version"]) is int and 1 <= job["version"] <= 2**53 - 1)
            tables = reply["response"].get("tables")
            require(
                type(tables) is list and len(tables) == 1 and type(tables[0]) is dict
            )
            columns = tables[0].get("columns")
            require(type(columns) is list)
            if type(column_index) is not int or not 0 <= column_index < len(columns):
                raise WorkspaceError("invalid_request", 422)
            brief = build(
                reply["response"],
                saved["input_message"]["content"],
                column_index,
                check,
            )
            check()
            records.authorize(conn, current, self.workspace.policy, job)
            check()
            result = {
                "schemaVersion": 1,
                "owner_id": str(session.user["id"]),
                "chat_id": str(saved["chat"]["id"]),
                "request_id": request_id,
                "assistant_message_id": str(reply["id"]),
                "job_version": job["version"],
                "brief": brief,
            }
            require(len(encoded(result)) <= 32768)
            check()
            return result
