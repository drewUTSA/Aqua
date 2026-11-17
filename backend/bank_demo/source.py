"""Immutable synthetic producer adapter; app identity/admission stay outside."""

from dataclasses import dataclass
from collections.abc import Callable

from workspace.errors import WorkspaceError


@dataclass(frozen=True)
class SyntheticReportSource:
    persona: str

    def __post_init__(self):
        if type(self.persona) is not str or self.persona not in {
            "none",
            "teller",
            "analyst",
            "manager",
        }:
            raise ValueError("bank_demo_source_invalid")

    def context(self, check: Callable[[], None]) -> dict:
        from mcp_demo import web
        from mcp_demo.protocol import actor_for

        check()
        result = web.context(actor_for(self.persona))
        check()
        return result

    def report(
        self, report_id: str, expected_source_revision: str, check: Callable[[], None]
    ) -> dict:
        from mcp_demo import web
        from mcp_demo.protocol import actor_for

        check()
        actor = actor_for(self.persona)
        if report_id not in web.REPORT_IDS:
            raise WorkspaceError("invalid_request", 422)
        if expected_source_revision != web.SOURCE_REVISION:
            raise WorkspaceError("revision_conflict", 409)
        if (
            report_id not in actor.scope.report_ids
            or "read_report" not in actor.scope.tool_ids
        ):
            raise WorkspaceError("access_denied", 403)
        result = web.report(actor, report_id)
        check()
        return result
