"""Fresh app-session/grant admission coordinates explicit note operations only."""

from collections.abc import Callable
from dataclasses import replace
import time

from auth.accounts import grant_state
from auth.security import UserSession
from context_notes import repository, rules
from context_notes.policy import (
    ContextNotesPolicy,
    LIMITS,
    MAX_RESPONSE_BYTES,
    SERVICE_SECONDS,
)
from privacy.retirement import advance
from workspace.database import guard
from workspace.errors import WorkspaceError
from workspace.service import Workspace

DATA_ACTIONS = frozenset({"detail", "create", "patch", "prepare"})
ACTIONS = DATA_ACTIONS | {"listing", "forget"}


class ContextNotes:
    def __init__(
        self,
        workspace: Workspace,
        policy: ContextNotesPolicy,
        *,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.workspace, self.policy, self.clock = workspace, policy, clock

    def perform(
        self,
        session: UserSession,
        action: str,
        *,
        note_id: str | None = None,
        body=None,
    ) -> tuple[dict, int]:
        """No content is published after a changed authority or expired lease."""
        if not self.policy.enabled:
            raise WorkspaceError("not_found")
        if action not in ACTIONS:
            raise ValueError("note_action_invalid")
        deadline = self.clock() + SERVICE_SECONDS

        def check() -> None:
            if self.clock() >= deadline:
                raise WorkspaceError("service_unavailable", 503)

        self.workspace.reserve(session)
        check()
        with self.workspace.storage.transaction() as conn:
            guard(conn, session, self.workspace.policy)
            conn.execute(
                "SELECT user_id FROM app.dataset_grants "
                "WHERE user_id=%s AND dataset_key=%s FOR SHARE",
                (session.user["id"], self.workspace.policy.dataset_key),
            )
            allowed, version = grant_state(
                conn, session.user["id"], self.workspace.policy
            )
            history = conn.execute(
                "SELECT history_generation FROM app.users WHERE id=%s",
                (session.user["id"],),
            ).fetchone()[0]
            current = replace(
                session,
                can_query=allowed,
                grant_version=version,
                dataset_key=self.workspace.policy.dataset_key,
                history_generation=history,
            )
            scope = {
                "id": rules.scope_id(
                    current.user["id"],
                    current.dataset_key,
                    version,
                    current.auth_epoch,
                    history,
                ),
                "can_use": allowed,
            }
            if body is not None and body.expected_scope_id != scope["id"]:
                raise WorkspaceError("scope_changed", 409)
            if action in DATA_ACTIONS and not allowed:
                raise WorkspaceError("access_denied", 403)
            check()
            payload, status = self._operation(
                conn, current, action, note_id, body, check
            )
            guard(conn, current, self.workspace.policy, data=action in DATA_ACTIONS)
            if grant_state(conn, current.user["id"], self.workspace.policy) != (
                allowed,
                version,
            ):
                raise WorkspaceError("scope_changed", 409)
            result = {
                "schemaVersion": 1,
                "owner_id": current.user["id"],
                "scope": scope,
                "unverified": True,
                "execution_enabled": False,
                **payload,
            }
            check()
            if len(rules.encode(result)) > MAX_RESPONSE_BYTES:
                raise WorkspaceError("service_unavailable", 503)
            check()
            return result, status

    def _operation(
        self, conn, current, action, note_id, body, check
    ) -> tuple[dict, int]:
        owner = current.user["id"]
        if action == "listing":
            items = []
            for item in repository.listing(conn, owner):
                check()
                items.append(
                    rules.metadata(
                        item,
                        allowed=rules.available(
                            item,
                            allowed=current.can_query,
                            dataset=current.dataset_key,
                            version=current.grant_version,
                        ),
                    )
                )
            return {"items": items, "limits": dict(LIMITS)}, 200
        if action == "create":
            item, status = repository.create(
                conn, owner, current.dataset_key, current.grant_version, body
            )
            return {"note": rules.note(item)}, status
        item = repository.get(conn, owner, rules.identifier(note_id))
        if action == "forget":
            deleted = repository.forget(conn, owner, item, body.revision)
            advance(conn, owner)
            return {"deleted": deleted}, 200
        if not rules.available(
            item,
            allowed=current.can_query,
            dataset=current.dataset_key,
            version=current.grant_version,
        ):
            raise WorkspaceError("not_found")
        if action == "detail":
            return {"note": rules.note(item)}, 200
        repository.check_revision(item, body.revision)
        if action == "patch":
            updated = repository.patch(conn, owner, item, body)
            advance(conn, owner)
            return {"note": rules.note(updated)}, 200
        # Explicit preparation returns ordinary editable text, never a tool call.
        canonical = rules.note(item)
        return {
            "source": {
                key: canonical[key] for key in ("id", "revision", "kind", "label")
            },
            "draft": canonical["body"],
            "requires_review": True,
        }, 200
