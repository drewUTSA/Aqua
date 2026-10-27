"""Opt-in synthetic analysis; no analytical SQL, provider or network is used."""

from typing import Any

FIXTURE_EMAIL = "p05-browser-reader@example.test"
DATASET = "p06-fixture-only-no-analytical-connection"
FAIL_ONCE = "P06 fixture transient failure"


class AnalysisFixture:
    def __init__(self, storage: Any, settings: Any) -> None:
        from auth.config import dataset_key

        self.storage, self.settings = storage, settings
        self.dataset = dataset_key(settings)
        self.owner: str | None = None
        self.retired = False
        self.executions = 0
        self.max_executions = 8
        self.attempts: dict[str, int] = {}

    def control(self, item: dict[str, Any]) -> dict[str, Any]:
        if set(item) != {"id", "kind"}:
            raise ValueError("fixture_analysis_control_invalid")
        kind = item["kind"]
        if kind == "workspace_stats":
            return {
                "id": item["id"],
                "kind": kind,
                "fake_executions": self.executions,
                "actual_provider_calls": 0,
            }
        if kind == "workspace_grant":
            if self.owner is not None or self.retired:
                raise ValueError("fixture_analysis_grant_replay")
            with self.storage.transaction() as conn:
                row = conn.execute(
                    "SELECT u.id FROM app.users u JOIN app.user_emails e ON e.user_id=u.id JOIN app.password_credentials p ON p.user_id=u.id WHERE u.status='active' AND e.email_key=%s AND e.is_primary AND e.verified_at IS NOT NULL AND e.verification_method='email'",
                    (FIXTURE_EMAIL,),
                ).fetchone()
                if row is None:
                    raise ValueError("fixture_analysis_account_unavailable")
                self.owner = str(row[0])
                conn.execute(
                    "INSERT INTO app.dataset_grants(user_id,dataset_key) VALUES(%s,%s)",
                    (self.owner, self.dataset),
                )
        elif kind == "workspace_revoke":
            if self.owner is None or self.retired:
                raise ValueError("fixture_analysis_revoke_invalid")
            with self.storage.transaction() as conn:
                row = conn.execute(
                    "UPDATE app.dataset_grants SET revoked_at=clock_timestamp() WHERE user_id=%s AND dataset_key=%s AND revoked_at IS NULL RETURNING user_id",
                    (self.owner, self.dataset),
                ).fetchone()
                if row is None:
                    raise ValueError("fixture_analysis_grant_unavailable")
            self.retired = True
        else:
            raise ValueError("fixture_analysis_control_invalid")
        return {"id": item["id"], "kind": kind, "enabled": not self.retired}

    def answer(
        self, question: str, model: str, session: Any, settings: Any
    ) -> dict[str, Any]:
        from nl2sql.response import outage_response

        if (
            self.owner is None
            or self.retired
            or session.user["id"] != self.owner
            or settings.database_url != DATASET
            or not session.can_query
            or model not in {"ollama", "gemini"}
            or len(question) > 2000
            or self.executions >= self.max_executions
        ):
            raise AssertionError("fixture_analysis_boundary_failed")
        # Prove the web submission released its private DB lease before work.
        with self.storage.transaction() as conn:
            if conn.execute("SELECT current_database(),current_user").fetchone() != (
                "aqua_app",
                "aqua_app_runtime",
            ):
                raise AssertionError("fixture_analysis_storage_invalid")
        self.executions += 1
        self.attempts[question] = self.attempts.get(question, 0) + 1
        if question == FAIL_ONCE and self.attempts[question] == 1:
            return outage_response(
                "model_unavailable",
                "Synthetic fixture transient failure. Retry the saved input.",
            )
        return {
            "status": "success",
            "sql": "SELECT 7 AS fixture_value",
            "model": "fixture-only",
            "message": "Synthetic fixture answer saved with its owned conversation.",
            "tables": [
                {
                    "id": "result",
                    "title": "Synthetic fixture result",
                    "columns": [
                        {
                            "key": "fixture_value",
                            "label": "Fixture value",
                            "type": "number",
                        }
                    ],
                    "rows": [{"fixture_value": 7}],
                }
            ],
            "visualizations": [],
            "kpis": [],
            "error": None,
        }
