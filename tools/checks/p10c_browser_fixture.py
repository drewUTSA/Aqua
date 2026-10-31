"""Closed synthetic Google/mail seam over real schema7 account API authority."""

import base64
from dataclasses import dataclass, field
import hashlib
import hmac
from http.cookies import SimpleCookie
import json
import re
import secrets
import time
from typing import Any
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

from p05_browser_protocol import GOOGLE_EMAIL, GOOGLE_SUBJECT, MAX_BODY, PATHS
from p06_browser_routes import workspace_route
from p10b_browser_fixture import ORIGIN, secure_origin, security_dispatch

OWNER = (GOOGLE_SUBJECT, GOOGLE_EMAIL)
CANDIDATE = ("p10c-fixture-google-candidate", "candidate.identity@example.test")
NEW_EMAIL = "p10c-new-reader@example.test"
PASSWORD_EMAIL = "p05-browser-reader@example.test"
TOKEN_PURPOSES = {"password_add", "email_change_new", "email_change_old"}
NOTICE_PURPOSES = {
    "password_changed",
    "password_added",
    "email_changed",
    "google_linked",
    "google_unlinked",
}
TOKEN = re.compile(r"v2\.[A-Za-z0-9_-]{43}\Z")
NONCE = re.compile(r"[A-Za-z0-9_-]{43}\Z")
MAX_ASSERTIONS = 8
MAX_TRACKED = 16
NEW_ROUTES = {
    "/api/v1/me/reauth/google-challenges": {"POST"},
    "/api/v1/me/reauth/google": {"POST"},
    "/api/v1/me/google-link-challenges": {"POST"},
    "/api/v1/me/google-link-candidates": {"POST"},
    "/api/v1/me/google-links": {"POST"},
    "/api/v1/me/password-enrollments": {"POST"},
    "/api/v1/me/email-change-requests": {"POST"},
    "/api/v1/me/password": {"POST", "PUT"},
    "/api/v1/me/email": {"PUT"},
    "/api/v1/me/notification-settings": {"GET", "PUT"},
}


def identifier(value: Any) -> str:
    if type(value) is not str or len(value) != 36:
        raise ValueError("fixture_identity_id_invalid")
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError):
        raise ValueError("fixture_identity_id_invalid") from None
    return value


def digest(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


def bound(settings: Any, token: str, scope: str) -> str:
    raw = hmac.new(
        settings.session_secret.encode(),
        ("aqua-v2:" + scope + ":" + token).encode(),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def identity_route(path: Any, method: Any) -> bool:
    if (
        type(path) is not str
        or type(method) is not str
        or len(path) > 2048
        or "\\" in path
        or any(ord(c) < 32 for c in path)
    ):
        return False
    parsed = urlsplit(path)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.fragment
        or not path.startswith("/api/")
    ):
        return False
    if parsed.path in NEW_ROUTES:
        return not parsed.query and method in NEW_ROUTES[parsed.path]
    if re.fullmatch(
        r"/api/v1/me/methods/google/[0-9a-f-]{36}/revocations", parsed.path
    ):
        try:
            identifier(parsed.path.split("/")[-2])
        except ValueError:
            return False
        return not parsed.query and method == "POST"
    if parsed.path in PATHS - {"/api/query"}:
        if parsed.query:
            try:
                values = parse_qsl(
                    parsed.query,
                    keep_blank_values=True,
                    strict_parsing=True,
                    max_num_fields=1,
                )
            except ValueError:
                return False
            if (
                parsed.path != "/api/v1/auth/bootstrap"
                or len(values) != 1
                or values[0][0] != "action"
                or values[0][1]
                not in {
                    "registration",
                    "verification",
                    "login",
                    "reset-request",
                    "reset",
                }
            ):
                return False
        return method in {"GET", "POST", "HEAD", "OPTIONS"}
    home_catalog = method == "GET" and parsed.path in {
        "/api/v1/chats",
        "/api/v1/projects",
        "/api/v1/starter-prompts",
    }
    return (parsed.path.startswith("/api/v1/me") or home_catalog) and workspace_route(
        path, method
    )


@dataclass(frozen=True)
class Challenge:
    kind: str
    id: str
    secret: bytes = field(repr=False)
    binding: bytes = field(repr=False)
    session: bytes | None = field(repr=False)


class IdentityFixture:
    """Assertions are fixed, one-use, transient and require actual issued rows."""

    def __init__(self, service: Any, settings: Any, analysis: Any) -> None:
        secure_origin(settings.app_origin)
        self.service, self.settings, self.analysis = service, settings, analysis
        self.cookies: dict[str, str] = {}
        self.challenges: dict[str, Challenge] = {}
        self.requests: dict[str, Challenge] = {}
        self.assertions: dict[str, tuple[str, Challenge, str]] = {}
        self.issued = self.consumed = 0
        if analysis is not None:
            analysis.max_executions = 0

    def metadata(self) -> dict:
        return {
            "mode": "closed_synthetic_assertion_registry",
            "schema_version": 7,
            "real_google_sdk_calls": 0,
            "real_mail_provider_calls": 0,
            "synthetic_google_assertions_issued": self.issued,
            "synthetic_google_assertions_consumed": self.consumed,
            "new_email": NEW_EMAIL,
            "security_fake_jobs": 0,
            "dns_socket_tls_transport_tested": False,
        }

    def clear(self) -> None:
        self.cookies.clear()
        self.challenges.clear()
        self.requests.clear()
        self.assertions.clear()

    def install(self) -> None:
        from auth import router
        import account.google_verification

        router.verify_google_token = self.verify
        account.google_verification.verify_google_token = self.verify

    def session(self) -> bytes | None:
        value = self.cookies.get("__Host-aqua_session", "")
        return digest(value) if TOKEN.fullmatch(value) else None

    def context_valid(
        self, context: Challenge, consumed: bool, identity: str = "owner"
    ) -> bool:
        if identity not in {"owner", "candidate"}:
            return False
        if context.session != self.session():
            return False
        name = (
            "__Host-aqua_login"
            if context.kind == "login"
            else (
                "__Host-aqua_account_action"
                if context.kind == "reauth"
                else "__Host-aqua_identity_action"
            )
        )
        cookie = self.cookies.get(name, "")
        if not TOKEN.fullmatch(cookie) or digest(cookie) != (
            context.secret if context.kind == "login" else context.binding
        ):
            return False
        state = "IS NOT NULL" if consumed else "IS NULL"
        with self.service.transaction() as conn:
            if context.kind == "login":
                row = conn.execute(
                    "SELECT id FROM app.auth_challenges WHERE purpose='google_login' AND secret_digest=%s AND binding_digest=%s AND consumed_at "
                    + state
                    + " AND expires_at>clock_timestamp()",
                    (context.secret, context.binding),
                ).fetchone()
            elif context.kind == "reauth":
                row = conn.execute(
                    "SELECT c.id FROM app.auth_challenges c JOIN app.sessions s ON s.user_id=c.user_id AND s.id=c.session_id JOIN app.users u ON u.id=s.user_id JOIN app.external_identities e ON e.user_id=u.id AND e.id=c.account_google_identity_id WHERE c.id=%s AND c.purpose='reauth' AND c.secret_digest=%s AND c.binding_digest=%s AND c.consumed_at "
                    + state
                    + " AND c.expires_at>clock_timestamp() AND s.token_digest=%s AND s.revoked_at IS NULL AND s.idle_expires_at>clock_timestamp() AND s.absolute_expires_at>clock_timestamp() AND u.status='active' AND u.auth_epoch=s.auth_epoch AND s.auth_epoch=c.account_auth_epoch AND e.is_active AND e.revision=c.account_google_identity_revision AND e.issuer='https://accounts.google.com' AND e.subject=%s AND e.observed_email_key=%s",
                    (
                        context.id,
                        context.secret,
                        context.binding,
                        context.session,
                        *(CANDIDATE if identity == "candidate" else OWNER),
                    ),
                ).fetchone()
            elif context.kind in {"link", "password_add", "email_change"}:
                claim = (
                    " AND r.claimed_at " + state + " AND r.verified_at IS NULL"
                    if context.kind == "link"
                    else ""
                )
                operation = "google_link" if context.kind == "link" else context.kind
                row = conn.execute(
                    "SELECT r.id FROM app.account_security_requests r JOIN app.sessions s ON s.user_id=r.user_id AND s.id=r.session_id JOIN app.users u ON u.id=s.user_id JOIN app.user_emails e ON e.user_id=u.id AND e.is_primary AND e.verified_at IS NOT NULL WHERE r.id=%s AND r.operation=%s AND r.secret_digest=%s AND r.binding_digest=%s AND r.consumed_at IS NULL AND r.expires_at>clock_timestamp() AND s.token_digest=%s AND s.revoked_at IS NULL AND s.idle_expires_at>clock_timestamp() AND s.absolute_expires_at>clock_timestamp() AND u.status='active' AND u.auth_epoch=s.auth_epoch AND s.auth_epoch=r.auth_epoch AND u.email_revision=r.source_email_revision AND e.id=r.source_email_id AND e.email_key=r.source_email_key AND (r.source_google_identity_id IS NULL OR EXISTS(SELECT 1 FROM app.external_identities g WHERE g.user_id=u.id AND g.id=r.source_google_identity_id AND g.is_active AND g.revision=r.source_google_identity_revision))"
                    + claim,
                    (
                        context.id,
                        operation,
                        context.secret,
                        context.binding,
                        context.session,
                    ),
                ).fetchone()
            else:
                return False
        return row is not None

    def assertion(self, item: dict) -> dict:
        if (
            set(item) != {"id", "kind", "nonce", "client_id", "identity"}
            or item.get("kind") != "google_assertion"
        ):
            raise ValueError("fixture_google_assertion_invalid")
        nonce, identity = item.get("nonce"), item.get("identity")
        if (
            type(nonce) is not str
            or not NONCE.fullmatch(nonce)
            or item.get("client_id") != self.settings.google_client_id
            or identity not in {"owner", "candidate"}
        ):
            raise ValueError("fixture_google_assertion_invalid")
        context = self.challenges.get(nonce)
        if context is None or not self.context_valid(context, False, identity):
            raise ValueError("fixture_google_provenance_invalid")
        if self.issued >= MAX_ASSERTIONS or len(self.assertions) >= MAX_ASSERTIONS:
            raise ValueError("fixture_google_assertion_limit")
        credential = "synthetic-google-" + secrets.token_urlsafe(32)
        self.assertions[credential] = (nonce, context, identity)
        del self.challenges[nonce]
        self.issued += 1
        return {
            "id": item["id"],
            "kind": "google_assertion",
            "credential": credential,
            "synthetic": True,
            "real_google_sdk_calls": 0,
        }

    def verify(self, credential: str, client_id: str) -> dict:
        if type(credential) is not str or client_id != self.settings.google_client_id:
            raise ValueError("fixture_google_credential_invalid")
        value = self.assertions.pop(credential, None)
        if value is None:
            raise ValueError("fixture_google_credential_invalid")
        nonce, context, identity = value
        if not self.context_valid(context, True, identity):
            raise ValueError("fixture_google_provenance_invalid")
        self.consumed += 1
        subject, email = CANDIDATE if identity == "candidate" else OWNER
        instant = int(time.time())
        return {
            "iss": "https://accounts.google.com",
            "aud": client_id,
            "sub": subject,
            "email": email,
            "email_verified": True,
            "name": "Synthetic identity reader",
            "picture": "",
            "nonce": nonce,
            "iat": instant,
            "exp": instant + 300,
        }

    def track(self, item: dict, result: dict) -> None:
        if result.get("status") != 200:
            return
        headers = result.get("headers", [])
        for name, value in headers:
            if name.lower() == "set-cookie":
                parsed = SimpleCookie()
                parsed.load(value)
                for key, morsel in parsed.items():
                    if morsel.value:
                        self.cookies[key] = morsel.value
                    else:
                        self.cookies.pop(key, None)
        path = urlsplit(item["path"]).path
        if path not in {
            "/api/auth/config",
            "/api/v1/me/reauth/google-challenges",
            "/api/v1/me/google-link-challenges",
            "/api/v1/me/password-enrollments",
            "/api/v1/me/email-change-requests",
        }:
            return
        body = json.loads(base64.b64decode(result["bodyBase64"], validate=True))
        if type(body) is not dict:
            raise ValueError("fixture_identity_response_invalid")
        if path == "/api/auth/config":
            secret = self.cookies.get("__Host-aqua_login", "")
            nonce = body.get("nonce")
            if (
                not TOKEN.fullmatch(secret)
                or body.get("client_id") != self.settings.google_client_id
                or nonce != bound(self.settings, secret, "google-nonce")
                or body.get("csrf_token") != bound(self.settings, secret, "login-csrf")
            ):
                raise ValueError("fixture_google_response_invalid")
            context = Challenge(
                "login", "", digest(secret), digest(body["csrf_token"]), self.session()
            )
        elif path.endswith(("password-enrollments", "email-change-requests")):
            secret, binding = body.get("request_token", ""), self.cookies.get(
                "__Host-aqua_identity_action", ""
            )
            request = identifier(body.get("request_id"))
            if (
                type(secret) is not str
                or not TOKEN.fullmatch(secret)
                or not TOKEN.fullmatch(binding)
                or self.session() is None
                or len(self.requests) >= MAX_TRACKED
            ):
                raise ValueError("fixture_mail_response_invalid")
            operation = (
                "password_add"
                if path.endswith("password-enrollments")
                else "email_change"
            )
            self.requests[request] = Challenge(
                operation, request, digest(secret), digest(binding), self.session()
            )
            return
        else:
            secret, nonce = body.get("challenge_token", ""), body.get("nonce")
            kind = "reauth" if path.endswith("reauth/google-challenges") else "link"
            binding = self.cookies.get(
                (
                    "__Host-aqua_account_action"
                    if kind == "reauth"
                    else "__Host-aqua_identity_action"
                ),
                "",
            )
            scope = (
                "account-google-nonce"
                if kind == "reauth"
                else "account-google-link-nonce"
            )
            if (
                type(secret) is not str
                or not TOKEN.fullmatch(secret)
                or not TOKEN.fullmatch(binding)
                or body.get("client_id") != self.settings.google_client_id
                or nonce != bound(self.settings, secret, scope)
                or self.session() is None
            ):
                raise ValueError("fixture_google_response_invalid")
            context = Challenge(
                kind,
                identifier(body.get("challenge_id")),
                digest(secret),
                digest(binding),
                self.session(),
            )
        if (
            type(nonce) is not str
            or not NONCE.fullmatch(nonce)
            or len(self.challenges) >= MAX_TRACKED
        ):
            raise ValueError("fixture_google_response_invalid")
        self.challenges[nonce] = context

    def mailbox(self, item: dict, deliver: Any, captured: list) -> dict:
        if (
            set(item) != {"id", "kind", "purpose", "request_id"}
            or item.get("purpose") not in TOKEN_PURPOSES
        ):
            raise ValueError("fixture_identity_mailbox_invalid")
        request = identifier(item.get("request_id"))
        context = self.requests.get(request)
        purpose = item["purpose"]
        if (
            context is None
            or (purpose == "password_add") != (context.kind == "password_add")
            or not self.context_valid(context, False)
        ):
            raise ValueError("fixture_identity_mailbox_provenance_invalid")
        for _ in range(8):
            selected = next(
                (
                    payload
                    for payload in captured
                    if payload.get("purpose") == purpose
                    and payload.get("request_id") == request
                ),
                None,
            )
            if selected is not None:
                if selected.get("to") not in {
                    OWNER[1],
                    CANDIDATE[1],
                    PASSWORD_EMAIL,
                    NEW_EMAIL,
                }:
                    raise ValueError("fixture_identity_mailbox_recipient_denied")
                expected = re.escape(
                    ORIGIN
                    + "/account-action/"
                    + purpose
                    + "#request="
                    + request
                    + "&token="
                )
                found = re.search(
                    expected + r"([A-Za-z0-9_-]{43})(?:\n|$)", selected.get("text", "")
                )
                if not found:
                    raise ValueError("fixture_identity_mailbox_envelope_invalid")
                from auth.mailpurposes import ACCOUNT_MAIL_SQL

                with self.service.transaction() as conn:
                    row = conn.execute(
                        "SELECT c.id FROM app.auth_challenges c WHERE c.account_request_id=%s AND c.purpose=%s AND c.target_email_key=%s AND c.secret_digest=%s AND c.consumed_at IS NULL AND "
                        + ACCOUNT_MAIL_SQL,
                        (request, purpose, selected["to"], digest(found[1])),
                    ).fetchone()
                if row is None:
                    raise ValueError("fixture_identity_mailbox_provenance_invalid")
                captured.remove(selected)
                return {
                    "id": item["id"],
                    "kind": "identity_mailbox",
                    "found": True,
                    "purpose": purpose,
                    "request_id": request,
                    "proof": found[1],
                    "link": ORIGIN
                    + "/account-action/"
                    + purpose
                    + "#request="
                    + request
                    + "&token="
                    + found[1],
                    "synthetic": True,
                    "body_exposed": False,
                    "real_provider_calls": 0,
                }
            deliver()
            time.sleep(1.05)
        return {
            "id": item["id"],
            "kind": "identity_mailbox",
            "found": False,
            "purpose": purpose,
            "request_id": request,
            "body_exposed": False,
        }

    def notice_status(self, item: dict) -> dict:
        if set(item) != {"id", "kind"}:
            raise ValueError("fixture_identity_notice_status_invalid")
        with self.service.transaction() as conn:
            rows = conn.execute(
                "SELECT purpose,state,count(*) FROM app.account_mail WHERE purpose=ANY(%s) GROUP BY purpose,state",
                (sorted(NOTICE_PURPOSES),),
            ).fetchall()
        result = {
            purpose: {"queued": 0, "completed": 0, "failed": 0}
            for purpose in sorted(NOTICE_PURPOSES)
        }
        for purpose, state, count in rows:
            if (
                purpose not in NOTICE_PURPOSES
                or state not in {"pending", "sending", "sent", "failed", "expired"}
                or type(count) is not int
                or not 0 <= count <= 4096
            ):
                raise ValueError("fixture_identity_notice_status_invalid")
            key = (
                "queued"
                if state in {"pending", "sending"}
                else "completed" if state == "sent" else "failed"
            )
            result[purpose][key] += count
        return {
            "id": item["id"],
            "kind": "identity_mail_status",
            "purposes": result,
            "body_exposed": False,
            "real_provider_calls": 0,
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
        if service is not self.service or analysis is not self.analysis:
            raise ValueError("fixture_identity_scope_invalid")
        kind = item.get("kind")
        if kind == "google_assertion":
            return self.assertion(item)
        if kind == "identity_mailbox":
            return self.mailbox(item, deliver, captured)
        if kind == "identity_mail_status":
            return self.notice_status(item)
        if kind == "workspace_stats":
            if set(item) != {"id", "kind"}:
                raise ValueError("fixture_identity_stats_invalid")
            result = security_dispatch(
                item, client, service, deliver, captured, analysis
            )
            result["identity_fixture"] = self.metadata()
            return result
        if kind == "mailbox":
            if set(item) != {"id", "kind", "purpose"} or item.get("purpose") not in {
                "verify_email",
                "reset_password",
            }:
                raise ValueError("fixture_identity_mail_purpose_denied")
            result = security_dispatch(
                item, client, service, deliver, captured, analysis
            )
            return {key: value for key, value in result.items() if key != "payload"}
        if kind != "request" or set(item) - {
            "id",
            "kind",
            "path",
            "method",
            "headers",
            "bodyBase64",
        }:
            raise ValueError("fixture_identity_control_denied")
        if not identity_route(item.get("path"), item.get("method")):
            raise ValueError("fixture_identity_route_denied")
        return self.forward(item, client)

    def forward(self, item: dict, client: Any) -> dict:
        headers = item.get("headers", [])
        if (
            not isinstance(headers, list)
            or len(headers) > 40
            or any(
                not isinstance(pair, list)
                or len(pair) != 2
                or any(
                    type(value) is not str or "\r" in value or "\n" in value
                    for value in pair
                )
                for pair in headers
            )
            or sum(len(name) + len(value) for name, value in headers) > 8192
        ):
            raise ValueError("fixture_identity_headers_invalid")
        cookies = [value for name, value in headers if name.lower() == "cookie"]
        if len(cookies) > 1:
            raise ValueError("fixture_identity_cookie_invalid")
        parsed = SimpleCookie()
        if cookies:
            parsed.load(cookies[0])
        self.cookies = {name: morsel.value for name, morsel in parsed.items()}
        body = base64.b64decode(item.get("bodyBase64", ""), validate=True)
        if len(body) > MAX_BODY:
            raise ValueError("fixture_body_limit")
        client.cookies.clear()
        try:
            response = client.request(
                item["method"],
                item["path"],
                headers=[
                    (name, value)
                    for name, value in headers
                    if name.lower() not in {"host", "content-length", "connection"}
                ],
                content=body,
                follow_redirects=False,
            )
            if len(response.content) > MAX_BODY:
                raise ValueError("fixture_response_body_limit")
            result = {
                "id": item["id"],
                "status": response.status_code,
                "headers": [
                    [name, value]
                    for name, value in response.headers.multi_items()
                    if name.lower() not in {"connection", "transfer-encoding"}
                ],
                "bodyBase64": base64.b64encode(response.content).decode(),
            }
            self.track(item, result)
            return result
        finally:
            client.cookies.clear()
