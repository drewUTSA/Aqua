"""Only confirmed independent headers can produce accepted deletion responses."""

import hmac
import threading

from auth.config import AuthDenied
from auth.security import UserSession
from auth.sessions import token_digest
from auth.store import IdentityStore
from account.identity_runtime import admit_action
from privacy import deletion_acceptance, deletion_admission, deletion_records as records
from privacy.database import PhysicalPool, global_lock
from privacy.deletion_contracts import public_job
from retirement import deletion_policy as policy
from retirement.client import ConfirmedAcceptance
from retirement.interlock import RetirementUnavailable
from retirement.revision import history_revision
from workspace.errors import WorkspaceError


class Deletions:
    def __init__(self, storage, auth_policy, settings, runtime, *, start=False):
        self.storage, self.policy, self.settings, self.runtime = (
            storage,
            auth_policy,
            settings,
            runtime,
        )
        self.stopped = threading.Event()
        self.thread = None
        self.pool = None
        if runtime.installed and runtime.ready:
            self.pool = PhysicalPool(storage.settings, 1)
        if start:
            self.start()

    def capable(self):
        return self.runtime.capable() and not self.stopped.is_set()

    def start(self):
        if self.pool is not None and self.thread is None:
            from privacy.deletion_worker import Worker

            self.thread = threading.Thread(
                target=Worker(self).loop, name="aqua-private-deletion", daemon=True
            )
            self.thread.start()

    def close(self):
        self.stopped.set()
        if self.thread is not None:
            self.thread.join(timeout=5)
        if (
            self.thread is None or not self.thread.is_alive()
        ) and self.pool is not None:
            self.pool.close()

    def owned(self, bearer, intent, receipt, scope=None):
        ticket = policy.receipt_digest(receipt)
        deletion_admission.admit(self.storage, bearer.digest)
        with self.storage.transaction() as conn:
            row = records.get(conn, intent)
            now = conn.execute("SELECT clock_timestamp()").fetchone()[0]
            if (
                row is None
                or row["receipt_revoked_at"] is not None
                or row["receipt_expires_at"] <= now
                or scope is not None
                and row["scope"] != scope
                or not hmac.compare_digest(
                    bytes(row["origin_session_digest"]), bearer.digest
                )
                or not hmac.compare_digest(bytes(row["receipt_digest"]), ticket)
            ):
                raise WorkspaceError("not_found")
            expected = policy.job_identifier(
                self.settings.session_secret,
                str(row["installation_id"]),
                str(row["user_id"]),
                str(row["intent_id"]),
                row["scope"],
                bearer.digest,
                ticket,
            )
            if str(row["id"]) != expected:
                raise WorkspaceError("not_found")
            return row

    def confirm(self, row):
        accepted = self.runtime.client.confirm_acceptance(
            str(row["user_id"]), str(row["intent_id"]), row["scope"]
        )
        if type(accepted) is not ConfirmedAcceptance or not records.same_original(
            row, accepted
        ):
            raise RetirementUnavailable()
        with self.storage.transaction() as conn:
            global_lock(conn)
            records.control(conn)
            conn.execute(
                "SELECT id FROM app.users WHERE id=%s FOR UPDATE", (row["user_id"],)
            )
            current = records.get(conn, str(row["intent_id"]), lock=True)
            if current is None:
                raise WorkspaceError("not_found")
            records.acknowledge(conn, current, accepted)
            return records.get(conn, str(row["intent_id"]))

    def envelope(self, row, accepted):
        return {
            "schemaVersion": 1,
            "user_id": str(row["user_id"]),
            "job": public_job(row, acceptance_confirmed=accepted),
            "history_revision": history_revision(
                self.settings.session_secret, str(row["user_id"]), row["history_floor"]
            ),
        }

    def status(self, bearer, intent, receipt):
        row = self.owned(bearer, intent, receipt)
        if self.runtime.client is None or not self.runtime.ready:
            raise WorkspaceError("service_unavailable", 503)
        try:
            row = self.confirm(row)
        except RetirementUnavailable:
            if row["state"] == "awaiting_authority":
                return self.envelope(row, False)
            raise WorkspaceError("service_unavailable", 503) from None
        return self.envelope(row, True)

    def create(self, bearer, body, passwords):
        if not self.capable():
            raise WorkspaceError("service_unavailable", 503)
        try:
            row = self.owned(bearer, body.intent_id, body.receipt_token, body.scope)
        except WorkspaceError as error:
            if error.code != "not_found":
                raise
        else:
            try:
                row = self.confirm(row)
            except RetirementUnavailable:
                raise WorkspaceError("retirement_pending", 503) from None
            return self.envelope(row, True), 200
        store = IdentityStore(self.storage, self.policy)
        try:
            stored = store.authenticate(bearer.digest)
        except AuthDenied:
            raise WorkspaceError("session_invalid", 401) from None
        if not hmac.compare_digest(stored.csrf_digest, token_digest(bearer.csrf)):
            raise WorkspaceError("session_invalid", 401)
        session = UserSession(
            stored.user,
            bearer.csrf,
            bearer.digest,
            stored.can_query,
            stored.grant_version,
            stored.auth_epoch,
            stored.dataset_key,
            stored.history_generation,
        )
        admit_action(passwords, session)
        committed = self.runtime.client.intent_transaction(
            self.storage,
            session.user["id"],
            body.intent_id,
            body.scope,
            lambda conn, known: deletion_acceptance.create(
                self,
                conn,
                session,
                body,
                policy.receipt_digest(body.receipt_token),
                known,
            ),
        )
        row = committed.value
        try:
            self.runtime.client.prepare(
                records.original(row),
                records.manifest(row, self.runtime.client.broker.key.key_id),
            )
            row = self.confirm(row)
        except RetirementUnavailable:
            raise WorkspaceError("retirement_pending", 503) from None
        return self.envelope(row, True), 202
