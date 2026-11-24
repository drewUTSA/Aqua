"""Short authenticated read; no model, analytical connection or saved answer."""

import json
import time
from collections.abc import Callable

from auth.security import UserSession
from bank_demo.calculations import CalculationRequest, calculate
from bank_demo.policy import BankDemoPolicy
from bank_demo.requirements import ReportRequirements
from bank_demo.source import SyntheticReportSource
from workspace.database import guard
from workspace.errors import WorkspaceError
from workspace.service import Workspace


class BankDemo:
    def __init__(
        self,
        workspace: Workspace,
        policy: BankDemoPolicy,
        *,
        clock: Callable[[], float] = time.perf_counter,
    ):
        self.workspace, self.policy, self.clock = workspace, policy, clock

    def read(
        self,
        session: UserSession,
        *,
        report_id: str | None = None,
        expected_source_revision: str | None = None,
        requirements: ReportRequirements | None = None,
        calculation: CalculationRequest | None = None,
    ) -> dict:
        if type(self.policy) is not BankDemoPolicy or not self.policy.enabled:
            raise WorkspaceError("not_found", 404)
        deadline = self.clock() + 2

        def check():
            if self.clock() >= deadline:
                raise WorkspaceError("service_unavailable", 503)

        check()
        self.workspace.reserve(session)
        check()
        with self.workspace.storage.transaction() as conn:
            guard(conn, session, self.workspace.policy, data=False)
            check()
            source = SyntheticReportSource(
                self.policy.for_account(str(session.user["id"]))
            )
            if calculation is not None:
                payload = calculate(calculation, source, check)
            elif report_id is None:
                payload = source.context(check)
            else:
                report = source.report(report_id, expected_source_revision, check)
                payload = (
                    {"result": report}
                    if requirements is None
                    else requirements.response(report)
                )
            check()
            # Recheck current session/account/history before publishing the result.
            guard(conn, session, self.workspace.policy, data=False)
            check()
            result = {
                "schemaVersion": 1,
                "owner_id": str(session.user["id"]),
                **payload,
            }
            raw = json.dumps(
                result, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
            if len(raw) > 32768:
                raise WorkspaceError("service_unavailable", 503)
            check()
            return result
