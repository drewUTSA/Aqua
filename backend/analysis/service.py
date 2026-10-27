"""Accept durable work and serve freshly authorized canonical snapshots."""

import hashlib
import threading
from uuid import uuid4
from auth.security import UserSession
from analysis import admission, context, events, lifecycle, records
from analysis.policy import TERMINAL
from workspace import submissions
from workspace.database import one
from workspace.errors import WorkspaceError
from workspace.service import Workspace
from pydantic import BaseModel
from auth.config import AuthPolicy
from storage.pool import Storage
from nl2sql.config import Settings
from analysis.engine import Engine


class Analysis:
    def __init__(
        self,
        storage: Storage,
        policy: AuthPolicy,
        secret: str,
        settings: Settings,
        *,
        engine: Engine | None = None,
        start: bool = False,
    ) -> None:
        from analysis.process import ProcessEngine
        from analysis.dispatch import Dispatcher

        self.storage, self.policy, self.secret, self.settings = (
            storage,
            policy,
            secret,
            settings,
        )
        self.engine = engine or ProcessEngine()
        self.dispatch = Dispatcher(self)
        self.stopped = threading.Event()
        self.threads = []
        if start:
            self.start()

    def enqueue(
        self,
        session: UserSession,
        body: BaseModel,
        *,
        chat_id: str | None = None,
        input_id: str | None = None,
    ) -> tuple[dict, int]:
        """Reserve input/job together; exact transport replay never repeats work."""
        Workspace(self.storage, self.policy, self.secret).reserve(session)
        with self.storage.transaction() as conn:
            current = records.authorize(conn, session, self.policy)
            request_id, created = submissions.begin(
                conn,
                current,
                body,
                chat_id=chat_id,
                input_id=input_id,
                default_model=self.settings.llm_provider,
            )
            if created:
                saved = one(
                    conn,
                    "SELECT r.chat_id,m.sequence,m.content,r.requested_model FROM app.analysis_requests r JOIN app.messages m ON m.user_id=r.user_id AND m.id=r.input_message_id WHERE r.user_id=%s AND r.id=%s",
                    (current.user["id"], request_id),
                )
                admission.reserve(
                    conn,
                    current.user["id"],
                    current.dataset_key,
                    saved["requested_model"],
                )
                history, digest = context.select(
                    conn,
                    current.user["id"],
                    str(saved["chat_id"]),
                    saved["sequence"],
                    current.dataset_key,
                    current.grant_version,
                )
                records.insert(
                    conn,
                    current,
                    request_id,
                    "",
                    saved["requested_model"],
                    history,
                    digest,
                    request_id=request_id,
                )
            snapshot = records.snapshot(conn, current, request_id)
        return snapshot, 200 if snapshot["request"]["state"] in TERMINAL else 202

    def snapshot(self, session: UserSession, request_id: str) -> dict:
        """Result ownership and current grants are checked again at delivery."""
        self.observe(session, "read")
        with self.storage.transaction() as conn:
            current = records.authorize(conn, session, self.policy)
            return records.snapshot(conn, current, request_id)

    def cancel(self, session: UserSession, request_id: str) -> tuple[dict, int]:
        """Acknowledge stopping separately from proof that the child has exited."""
        self.observe(session, "cancel")
        with self.storage.transaction() as conn:
            current = records.authorize(conn, session, self.policy)
            job = records.get(conn, current.user["id"], request_id, lock=True)
            if not job["request_id"]:
                raise WorkspaceError("not_found")
            admission.lock(conn)
            if job["state"] == "queued":
                job = lifecycle.terminate(conn, job, "cancelled", reaped=True)
            elif job["state"] == "running":
                conn.execute(
                    "UPDATE app.analysis_jobs SET cancel_requested=true WHERE id=%s",
                    (job["id"],),
                )
                job = events.emit(conn, job, "cancelling", "cancelling")
            saved = records.snapshot(conn, current, request_id)
            return saved, 200 if job["state"] in TERMINAL else 202

    def observe(self, session: UserSession, operation: str) -> None:
        # Commit before item lookup: failed/foreign IDs cannot roll this budget
        # back. Observation never extends the initiating session's idle expiry.
        with self.storage.transaction() as conn:
            records.authorize(conn, session, self.policy)
            admission.observe(conn, session.user["id"], operation)

    def legacy(
        self, session: UserSession, question: str, model: str | None
    ) -> tuple[dict, int]:
        job_id = str(uuid4())
        with self.storage.transaction() as conn:
            current = records.authorize(conn, session, self.policy)
            admission.reserve(
                conn,
                current.user["id"],
                current.dataset_key,
                model or self.settings.llm_provider,
            )
            counts = conn.execute(
                "SELECT count(*),count(*) FILTER(WHERE user_id=%s) FROM app.analysis_jobs WHERE request_id IS NULL",
                (current.user["id"],),
            ).fetchone()
            if counts[0] >= 10000 or counts[1] >= 1000:
                raise WorkspaceError("capacity_reached", 429)
            records.insert(
                conn,
                current,
                job_id,
                question,
                model or self.settings.llm_provider,
                [],
                hashlib.sha256(context.encode([])).digest(),
                request_id=None,
            )
        # The legacy client keeps its final JSON contract while sharing every
        # job/child/admission fence. It never creates an invisible history chat.
        while not self.stopped.is_set():
            self.dispatch.tick(preferred=job_id)
            with self.storage.transaction() as conn:
                current = records.authorize(conn, session, self.policy)
                job = records.get(conn, current.user["id"], job_id)
                if job["state"] in TERMINAL:
                    if job["response"] is not None:
                        return job["response"], job["http_status"]
                    return lifecycle.unavailable(job["state"])
            self.stopped.wait(0.1)
        return lifecycle.unavailable("interrupted")

    def tick(self) -> bool:
        return self.dispatch.tick()

    def start(self) -> None:
        if self.threads:
            return
        for index in range(2):
            thread = threading.Thread(
                target=self.dispatch.loop, name=f"aqua-analysis-{index}", daemon=True
            )
            self.threads.append(thread)
            thread.start()

    def close(self) -> None:
        self.stopped.set()
        self.engine.close()
        for thread in self.threads:
            thread.join(timeout=5)
