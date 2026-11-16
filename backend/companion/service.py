"""Authenticated help reads share existing admission, never analysis execution."""

import time
from collections.abc import Callable

from auth.accounts import grant_state
from auth.security import UserSession
from companion.application import application_context, help_choice
from companion.data import PACK, REVIEWED_SHA256
from companion.data_contract import CompanionDenied, _encode, _text
from companion.knowledge import Knowledge, load_pack, lookup
from workspace.database import guard
from workspace.errors import WorkspaceError
from workspace.service import Workspace

ABSTAIN = "I could not find one clear answer in the reviewed Aqua help. Ask about questions, results, charts, projects, settings, account access or privacy."


class Help:
    def __init__(
        self,
        workspace: Workspace,
        *,
        pack: Knowledge | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.workspace, self.clock = workspace, clock
        self.pack = pack

    def read(self, session: UserSession, *, question: str | None = None) -> dict:
        """Fresh guard and response assembly share a short, provider-free lease."""
        deadline = self.clock() + 2

        def check() -> None:
            if self.clock() >= deadline:
                raise WorkspaceError("service_unavailable", 503)

        pack = (
            load_pack(PACK, reviewed_sha256=REVIEWED_SHA256)
            if self.pack is None
            else self.pack
        )
        check()
        self.workspace.reserve(session)
        check()
        with self.workspace.storage.transaction() as conn:
            guard(conn, session, self.workspace.policy, data=False)
            check()
            if question is None:
                allowed, _ = grant_state(
                    conn, session.user["id"], self.workspace.policy
                )
                tools = [{"id": "app_help", "behavior": "reviewed_lookup"}]
                if allowed:
                    tools.append(
                        {"id": "authorized_question", "behavior": "seed_draft"}
                    )
                result = {
                    "schemaVersion": 1,
                    "advisory": True,
                    "selection": "explicit",
                    "pack_revision": pack.revision,
                    "capabilities": tools,
                }
            else:
                if not _text(question, 8000) or len(question) > 2000:
                    raise WorkspaceError("invalid_request", 422)
                found = lookup(pack, question, check=check)
                citations, message = [], ABSTAIN
                if found is not None:
                    context = application_context(session, pack)
                    help_choice(
                        _encode(
                            {
                                "schemaVersion": 1,
                                "choices": [
                                    {
                                        "capability_id": "app_help",
                                        "artifact_id": found.id,
                                    }
                                ],
                            }
                        ),
                        context=context,
                        current=context,
                        now=context.created_at,
                    )
                    citations = [
                        {
                            "id": found.id,
                            "title": found.title,
                            "revision": pack.revision,
                        }
                    ]
                    message = found.text
                result = {
                    "schemaVersion": 1,
                    "status": "answered" if found else "abstained",
                    "capability_id": "app_help",
                    "method": "reviewed_lookup",
                    "message": message,
                    "citations": citations,
                    "pack_revision": pack.revision,
                }
            check()
            if len(_encode(result)) > 32768:
                raise CompanionDenied("help_response_budget")
            return result
