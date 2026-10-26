"""Keep database ownership transactions separate from synchronous model work."""

from dataclasses import replace
from collections.abc import Callable
from typing import Any
from pydantic import BaseModel
from psycopg import Connection
from auth.config import AuthPolicy
from storage.pool import Storage
from nl2sql.config import Settings

from auth.accounts import grant_state
from auth.security import UserSession
from workspace import submissions, completion
from workspace.database import admit, guard
from workspace.errors import WorkspaceError


class Workspace:
    def __init__(self, storage: Storage, policy: AuthPolicy, secret: str) -> None:
        self.storage, self.policy, self.secret = storage, policy, secret

    def reserve(self, session: UserSession) -> None:
        with self.storage.transaction() as conn:
            guard(conn, session, self.policy)
            admit(conn, session.user["id"])

    def apply(
        self,
        session: UserSession,
        operation: Callable[[Connection, UserSession], Any],
        *,
        mutate: bool = False,
    ) -> Any:
        if mutate:
            self.reserve(session)
        with self.storage.transaction() as conn:
            guard(conn, session, self.policy, mutate=mutate)
            completion.interrupt(conn, session.user["id"])
            conn.execute(
                "SELECT user_id FROM app.dataset_grants WHERE user_id=%s AND dataset_key=%s FOR SHARE",
                (session.user["id"], self.policy.dataset_key),
            )
            allowed, version = grant_state(conn, session.user["id"], self.policy)
            current = replace(session, can_query=allowed, grant_version=version)
            return operation(conn, current)

    def submit(
        self,
        session: UserSession,
        body: BaseModel,
        runner: Callable,
        settings: Settings,
        *,
        chat_id: str | None = None,
        input_id: str | None = None,
    ) -> tuple[dict, int]:
        self.reserve(session)
        with self.storage.transaction() as conn:
            guard(conn, session, self.policy, mutate=True, data=True)
            completion.interrupt(conn, session.user["id"])
            request_id, created = submissions.begin(
                conn,
                session,
                body,
                chat_id=chat_id,
                input_id=input_id,
                default_model=settings.llm_provider,
            )
            saved = completion.snapshot(conn, session.user["id"], request_id, session)
        if not created:
            return saved, 202 if saved["request"]["state"] == "pending" else 200
        # The application DB lease has ended before schema/model/analytical I/O.
        try:
            response = completion.execute(
                runner,
                saved["input_message"]["content"],
                saved["assistant_message"]["model_id"],
                session,
                settings,
            )
        except Exception:
            with self.storage.transaction() as conn:
                completion.interrupt(conn, session.user["id"], request_id)
            raise WorkspaceError("service_unavailable", 503) from None
        try:
            with self.storage.transaction() as conn:
                guard(conn, session, self.policy, mutate=True, data=True)
                completion.finish(conn, session, request_id, response)
                saved = completion.snapshot(
                    conn, session.user["id"], request_id, session
                )
        except WorkspaceError:
            with self.storage.transaction() as conn:
                completion.interrupt(conn, session.user["id"], request_id)
            raise
        return saved, 201 if chat_id is None else 200
