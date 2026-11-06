"""Closed browser controls over actual schema9 routes and signed authority."""

import base64
import json
import re
from urllib.parse import urlsplit
from typing import Any

from p05_browser_protocol import GOOGLE_SUBJECT, MAX_BODY
from p06_browser_routes import workspace_route
from p10c_browser_fixture import IdentityFixture, identifier
from p11b_browser_authority import Authority

PATH = "/api/v1/me/data-deletions"
QUESTIONS = frozenset({"P08 chart primitives", "P08 text explanation"})


def deletion_route(path: Any, method: Any) -> bool:
    if (
        type(path) is not str
        or len(path) > 2048
        or "\\" in path
        or any(ord(value) < 32 for value in path)
    ):
        return False
    parsed = urlsplit(path)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or method != "POST"
    ):
        return False
    if path == PATH:
        return True
    if not path.startswith(PATH + "/by-intent/"):
        return False
    try:
        identifier(path[len(PATH + "/by-intent/") :])
    except ValueError:
        return False
    return True


def question_body(item: dict) -> None:
    raw = base64.b64decode(item.get("bodyBase64", ""), validate=True)
    if len(raw) > MAX_BODY:
        raise ValueError("fixture_body_limit")
    body = json.loads(raw)
    if (
        type(body) is not dict
        or set(body) - {"client_request_id", "question", "model"}
        or body.get("question") not in QUESTIONS
        or body.get("model") not in {"ollama", "gemini"}
    ):
        raise ValueError("fixture_deletion_question_denied")
    identifier(body.get("client_request_id"))


class DeletionFixture(IdentityFixture):
    def __init__(self, service: Any, settings: Any, analysis: Any) -> None:
        super().__init__(service, settings, analysis)
        self.owner = self.relogin = None
        self.relogin_denied = False
        self.starts = self.reconciles = self.stale_writes = 0
        analysis.max_executions = 4
        self.authority = None

    def install(self) -> None:
        super().install()
        import main

        self.authority = Authority(self.service, self.settings)
        main.app.state.retirement = self.authority.runtime
        main.app.state.deletions = self.authority.service

    def metadata(self) -> dict:
        return {
            **super().metadata(),
            "security_fake_jobs": self.analysis.started,
            "personal_deletion_fixture": True,
            "schema_version": 9,
            "actual_independent_authority": True,
        }

    def clear(self) -> None:
        super().clear()
        if self.authority is not None:
            self.authority.close()

    def track(self, item: dict, result: dict) -> None:
        super().track(item, result)
        path, status = item["path"], result.get("status")
        if path == "/api/auth/google" and status == 200:
            value = json.loads(base64.b64decode(result["bodyBase64"]))
            selected = identifier(value["user"]["id"])
            if self.owner is None:
                if value["can_query"] is not True:
                    raise ValueError("fixture_initial_legacy_grant_missing")
                with self.service.transaction() as conn:
                    if conn.execute(
                        "SELECT approval_kind,approval_evidence FROM app.dataset_grants WHERE user_id=%s",
                        (selected,),
                    ).fetchone() != ("google_subject", GOOGLE_SUBJECT):
                        raise ValueError("fixture_initial_legacy_grant_invalid")
                self.owner = self.analysis.owner = selected
            else:
                self.relogin = selected
                self.relogin_denied = (
                    selected != self.owner and value["can_query"] is False
                )
        if path == PATH:
            self.starts += 1
        elif path.startswith(PATH + "/by-intent/"):
            self.reconciles += 1
        elif path == "/api/v1/chats" and item["method"] == "POST" and status == 409:
            self.stale_writes += 1
        if self.starts > 2 or self.reconciles > 12 or self.stale_writes > 2:
            raise ValueError("fixture_deletion_operation_bound")

    def stats(self, request_id: str | int) -> dict:
        counts = {}
        with self.service.transaction() as conn:
            for table in (
                "users",
                "chats",
                "messages",
                "analysis_requests",
                "analysis_jobs",
                "visual_results",
                "sessions",
                "dataset_grants",
                "external_identities",
                "user_emails",
                "user_preferences",
            ):
                key = "id" if table == "users" else "user_id"
                count = conn.execute(
                    f"SELECT count(*) FROM app.{table} WHERE {key}=%s", (self.owner,)
                ).fetchone()[0]
                if type(count) is not int or not 0 <= count <= 128:
                    raise ValueError("fixture_deletion_metadata_bound")
                counts[table] = count
            jobs = conn.execute(
                "SELECT state FROM app.deletion_jobs WHERE user_id=%s ORDER BY created_at",
                (self.owner,),
            ).fetchall()
            if len(jobs) > 2:
                raise ValueError("fixture_deletion_job_bound")
            retained = conn.execute(
                "SELECT count(*) FROM app.retirement_intents WHERE user_id=%s AND authority_sequence IS NOT NULL",
                (self.owner,),
            ).fetchone()[0]
            regranted = (
                conn.execute(
                    "SELECT count(*) FROM app.dataset_grants WHERE user_id=%s",
                    (self.relogin,),
                ).fetchone()[0]
                if self.relogin
                else 0
            )
        return {
            "id": request_id,
            "kind": "deletion_stats",
            "counts": counts,
            "count_scope": "original_retired_owner",
            "states": [row[0] for row in jobs],
            "retained_signed_intents": retained,
            "create_posts": self.starts,
            "reconcile_posts": self.reconciles,
            "stale_write_denials": self.stale_writes,
            "bounded_worker_ticks": self.authority.ticks,
            "signed_publisher_cycles": self.authority.publishes,
            "new_uuid_relogin_denied": self.relogin_denied,
            "relogin_grants": regranted,
            "actual_independent_authority": True,
            "synthetic_authority": False,
            "real_provider_calls": 0,
            "append_only_ioctl_seam": True,
            "physical_mail_mount_seam": True,
            "p08_presentation_fixture": True,
        }

    def dispatch(
        self,
        item: dict,
        client: Any,
        service: Any,
        deliver: Any,
        captured: list,
        analysis: Any,
    ) -> dict:
        kind = item.get("kind")
        if kind in {"deletion_publish", "deletion_purge", "deletion_stats"}:
            if set(item) != {"id", "kind"} or self.owner is None:
                raise ValueError("fixture_deletion_control_denied")
            if kind == "deletion_publish":
                self.authority.publish()
            elif kind == "deletion_purge":
                self.authority.purge()
            return self.stats(item["id"])
        if kind == "workspace_stats":
            result = super().dispatch(
                item, client, service, deliver, captured, analysis
            )
            result["p08_presentation_fixture"] = True
            result["personal_deletion_fixture"] = True
            return result
        if kind == "request" and set(item) <= {
            "id",
            "kind",
            "path",
            "method",
            "headers",
            "bodyBase64",
        }:
            path, method = item.get("path"), item.get("method")
            if deletion_route(path, method):
                return self.forward(item, client)
            if workspace_route(path, method) and not path.startswith("/api/v1/me/"):
                if method == "GET" and re.fullmatch(
                    r"/api/v1/analysis-requests/[0-9a-f-]{36}/events", path
                ):
                    from p05_browser_messages import dispatch

                    return dispatch(item, client, service, deliver, captured, analysis)
                if method == "POST":
                    if path != "/api/v1/chats":
                        raise ValueError("fixture_deletion_workspace_write_denied")
                    question_body(item)
                elif method != "GET":
                    raise ValueError("fixture_deletion_workspace_write_denied")
                return self.forward(item, client)
        return super().dispatch(item, client, service, deliver, captured, analysis)
