"""Actual small private exports over the existing bounded one-loop API fixture."""

import base64
import json
from urllib.parse import urlsplit

from p10c_browser_fixture import IdentityFixture, identifier

EXPORTS = "/api/v1/me/data-exports"
PROJECT_MARKER = "Synthetic private export project"


def project_setup_body(item):
    if set(item) - {"id", "kind", "path", "method", "headers", "bodyBase64"}:
        raise ValueError("fixture_export_project_control_denied")
    encoded = item.get("bodyBase64")
    if type(encoded) is not str or len(encoded) > 684:
        raise ValueError("fixture_export_project_body_invalid")

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("fixture_export_project_body_invalid")
            value[key] = item
        return value

    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > 512:
            raise ValueError
        body = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
        if (
            type(body) is not dict
            or set(body) != {"client_request_id", "name"}
            or body["name"] != PROJECT_MARKER
        ):
            raise ValueError
        identifier(body["client_request_id"])
    except (ValueError, UnicodeError):
        raise ValueError("fixture_export_project_body_invalid") from None


def export_route(path, method):
    if (
        type(path) is not str
        or len(path) > 2048
        or "\\" in path
        or any(ord(c) < 32 for c in path)
    ):
        return False
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.fragment or parsed.query:
        return False
    if parsed.path == EXPORTS:
        return method in {"GET", "POST"}
    parts = parsed.path.split("/")
    if parts[:5] != ["", "api", "v1", "me", "data-exports"]:
        return False
    if len(parts) == 7 and parts[5] == "by-intent":
        selected = parts[6]
    elif len(parts) in {6, 7} and (len(parts) == 6 or parts[6] == "download"):
        selected = parts[5]
    else:
        return False
    try:
        identifier(selected)
    except ValueError:
        return False
    return method == "GET"


class PrivacyFixture(IdentityFixture):
    def __init__(self, service, settings, analysis):
        super().__init__(service, settings, analysis)
        self.starts = self.downloads = 0
        self.project_setup_used = False

    def metadata(self):
        return {
            **super().metadata(),
            "schema_version": 8,
            "personal_export_fixture": True,
        }

    def export_metadata(self):
        return {
            "starts": self.starts,
            "downloads": self.downloads,
            "real_provider_calls": 0,
            "body_exposed": False,
        }

    def track(self, item, result):
        super().track(item, result)
        if (
            item["path"] == EXPORTS
            and item["method"] == "POST"
            and result.get("status") == 202
        ):
            self.starts += 1
        if (
            item["path"].startswith(EXPORTS + "/")
            and item["path"].endswith("/download")
            and item["method"] == "GET"
            and result.get("status") == 200
        ):
            self.downloads += 1
        if self.starts > 8 or self.downloads > 8:
            raise ValueError("fixture_export_operation_bound")

    def dispatch(self, item, client, service, deliver, captured, analysis):
        if service is not self.service or analysis is not self.analysis:
            raise ValueError("fixture_export_scope_invalid")
        if (
            item.get("kind") == "request"
            and item.get("path") == "/api/v1/projects"
            and item.get("method") == "POST"
        ):
            project_setup_body(item)
            if self.project_setup_used:
                raise ValueError("fixture_export_project_setup_already_used")
            self.project_setup_used = True
            # Only fixed synthetic content is admitted. Browser cookies, Origin
            # and captured CSRF still reach the actual owned project API intact.
            return self.forward(item, client)
        if item.get("kind") == "export_stats":
            if set(item) != {"id", "kind"}:
                raise ValueError("fixture_export_control_denied")
            counts = {"retained_jobs": 0, "ready_jobs": 0, "stored_bytes": 0}
            token = self.session()
            if token is not None:
                with service.transaction() as conn:
                    row = conn.execute(
                        "SELECT s.id,s.user_id,s.auth_epoch,u.privacy_epoch FROM app.sessions s JOIN app.users u ON u.id=s.user_id WHERE s.token_digest=%s AND s.revoked_at IS NULL AND s.idle_expires_at>clock_timestamp() AND s.absolute_expires_at>clock_timestamp() AND u.status='active' AND s.auth_epoch=u.auth_epoch",
                        (token,),
                    ).fetchone()
                    if row is not None:
                        result = conn.execute(
                            "SELECT count(*),count(*) FILTER(WHERE state='ready' AND expires_at>clock_timestamp()),COALESCE(sum(output_bytes),0) FROM app.data_exports WHERE session_id=%s AND user_id=%s AND auth_epoch=%s AND privacy_epoch=%s",
                            row,
                        ).fetchone()
                        if (
                            len(result) != 3
                            or any(type(value) is not int for value in result)
                            or not 0 <= result[0] <= 5
                            or not 0 <= result[1] <= 1
                            or not 0 <= result[2] <= 33554432
                        ):
                            raise ValueError("fixture_export_metadata_bound")
                        counts = dict(zip(counts, result, strict=True))
            return {
                "id": item["id"],
                "kind": "export_stats",
                **self.export_metadata(),
                **counts,
                "owner_bound": True,
            }
        if item.get("kind") == "workspace_stats":
            result = super().dispatch(
                item, client, service, deliver, captured, analysis
            )
            result["export_fixture"] = self.export_metadata()
            return result
        if item.get("kind") == "request" and export_route(
            item.get("path"), item.get("method")
        ):
            if set(item) - {"id", "kind", "path", "method", "headers", "bodyBase64"}:
                raise ValueError("fixture_export_request_invalid")
            return self.forward(item, client)
        return super().dispatch(item, client, service, deliver, captured, analysis)
