"""Closed synthetic note controls; no request-selected owner/dataset/execution."""

import re
from urllib.parse import parse_qsl, urlsplit

from p05_browser_protocol import GOOGLE_EMAIL
from p06_browser_analysis import FIXTURE_EMAIL

DATASET = "context-notes-browser-fixture-only-no-analytical-connection"
NOTES = "/api/v1/me/context-notes"
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
SHELL = {
    "/api/health",
    "/api/models",
    "/api/auth/config",
    "/api/auth/me",
    "/api/auth/methods",
    "/api/v1/me",
    "/api/v1/me/preferences",
    "/api/v1/me/notification-settings",
    "/api/v1/starter-prompts",
    "/api/v1/companion/capabilities",
}
AUTH_POSTS = {
    "/api/v1/auth/registrations",
    "/api/v1/auth/email-verifications",
    "/api/v1/auth/password-login",
    "/api/auth/google",
    "/api/auth/logout",
}
LISTS = {
    "/api/v1/me/saved-prompts": {"cursor", "limit"},
    "/api/v1/projects": {"cursor", "limit"},
    "/api/v1/chats": {"cursor", "limit", "archived", "project_id"},
}


def notes_route(path, method):
    """No broad prefix or generic workspace fallback, even in fixture mode."""
    if (
        type(path) is not str
        or type(method) is not str
        or len(path) > 2048
        or "\\" in path
        or any(ord(value) < 32 or ord(value) == 127 for value in path)
    ):
        return False
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or "#" in path or "%" in parsed.path:
        return False
    try:
        pairs = parse_qsl(
            parsed.query, strict_parsing=True, keep_blank_values=True, max_num_fields=6
        )
    except ValueError:
        return False
    if len({key for key, _ in pairs}) != len(pairs):
        return False
    query = dict(pairs)
    if parsed.path == "/api/v1/auth/bootstrap":
        return (
            method == "GET"
            and set(query) == {"action"}
            and query["action"]
            in {
                "registration",
                "verification",
                "login",
            }
        )
    if parsed.path in LISTS:
        if method != "GET" or set(query) - LISTS[parsed.path]:
            return False
        return all(
            (key == "limit" and value == "20")
            or (key == "cursor" and 0 < len(value) <= 1024)
            or (key == "archived" and value in {"true", "false"})
            or (key == "project_id" and re.fullmatch(UUID, value) is not None)
            for key, value in query.items()
        )
    if parsed.query:
        return False
    if parsed.path in SHELL:
        return method == "GET"
    if parsed.path in AUTH_POSTS:
        return method == "POST"
    if parsed.path == NOTES:
        return method in {"GET", "POST"}
    if re.fullmatch(NOTES + "/" + UUID, parsed.path):
        return method in {"GET", "PATCH"}
    return (
        method == "POST"
        and re.fullmatch(NOTES + "/" + UUID + "/(?:forget|prepare)", parsed.path)
        is not None
    )


class NoExecutionEngine:
    def __init__(self):
        self.calls = 0

    def run(self, payload, control):
        self.calls += 1
        raise AssertionError("fixture_notes_engine_forbidden")

    def close(self):
        pass


class NotesFixture:
    def __init__(self, storage, settings):
        from auth.config import dataset_key

        if settings.database_url != DATASET:
            raise ValueError("fixture_notes_dataset_invalid")
        self.storage, self.settings = storage, settings
        self.dataset = dataset_key(settings)
        self.owner = None
        self.state = "ungranted"
        self.stats_reads = 0
        self.mail_reads = 0
        self.engine = NoExecutionEngine()
        self.enqueue_calls = 0
        self.provider_calls = 0
        self.forbidden_requests = 0

    def no_enqueue(self, *args, **kwargs):
        self.enqueue_calls += 1
        raise AssertionError("fixture_notes_enqueue_forbidden")

    def no_provider(self, *args, **kwargs):
        self.provider_calls += 1
        raise AssertionError("fixture_notes_provider_forbidden")

    def install(self, main):
        from analysis.service import Analysis
        from auth.config import load_auth_policy
        from bank_demo.policy import BankDemoPolicy
        from companion.policy import CompanionPolicy
        from context_notes.policy import ContextNotesPolicy

        main.app.state.bank_demo_policy = BankDemoPolicy()
        main.app.state.companion_policy = CompanionPolicy()
        main.app.state.context_notes_policy = ContextNotesPolicy(True)
        runtime = Analysis(
            self.storage,
            load_auth_policy(self.settings),
            self.settings.session_secret,
            self.settings,
            engine=self.engine,
        )
        runtime.enqueue = self.no_enqueue
        runtime.legacy = self.no_enqueue
        main.app.state.analysis = runtime
        main.answer_question = self.no_provider
        main.get_schema = self.no_provider

    def _owner(self, conn):
        row = conn.execute(
            "SELECT u.id FROM app.users u JOIN app.user_emails e ON e.user_id=u.id "
            "JOIN app.password_credentials p ON p.user_id=u.id "
            "WHERE u.status='active' AND e.email_key=%s AND e.is_primary "
            "AND e.verified_at IS NOT NULL AND e.verification_method='email' "
            "FOR UPDATE OF u",
            (FIXTURE_EMAIL,),
        ).fetchone()
        if row is None or self.owner is not None and str(row[0]) != self.owner:
            raise ValueError("fixture_notes_owner_unavailable")
        return str(row[0])

    def control(self, item):
        if set(item) != {"id", "kind"}:
            raise ValueError("fixture_notes_control_invalid")
        kind = item["kind"]
        if kind == "notes_stats":
            return self.stats(item["id"])
        expected = {
            "notes_grant": "ungranted",
            "notes_revoke": "granted",
            "notes_regrant": "revoked",
            "notes_history_advance": "regranted",
        }
        if kind not in expected or self.state != expected[kind]:
            raise ValueError("fixture_notes_control_order")
        with self.storage.transaction() as conn:
            owner = self._owner(conn)
            if kind == "notes_grant":
                row = conn.execute(
                    "INSERT INTO app.dataset_grants(user_id,dataset_key) "
                    "VALUES(%s,%s) ON CONFLICT DO NOTHING RETURNING user_id",
                    (owner, self.dataset),
                ).fetchone()
            elif kind == "notes_history_advance":
                row = conn.execute(
                    "UPDATE app.users SET history_generation=history_generation+1 "
                    "WHERE id=%s AND history_generation=1 RETURNING id",
                    (owner,),
                ).fetchone()
            else:
                revoked = kind == "notes_revoke"
                row = conn.execute(
                    "UPDATE app.dataset_grants SET revoked_at="
                    + ("clock_timestamp()" if revoked else "NULL")
                    + " WHERE user_id=%s AND dataset_key=%s AND revoked_at IS "
                    + ("NULL" if revoked else "NOT NULL")
                    + " RETURNING user_id",
                    (owner, self.dataset),
                ).fetchone()
            if row is None:
                raise ValueError("fixture_notes_transition_unavailable")
        self.owner = owner
        self.state = {
            "notes_grant": "granted",
            "notes_revoke": "revoked",
            "notes_regrant": "regranted",
            "notes_history_advance": "history_advanced",
        }[kind]
        return {
            "id": item["id"],
            "kind": kind,
            **(
                {"advanced": True}
                if kind == "notes_history_advance"
                else {"enabled": kind != "notes_revoke"}
            ),
        }

    def stats(self, identifier):
        if self.stats_reads >= 4:
            raise ValueError("fixture_notes_stats_limit")
        self.stats_reads += 1
        with self.storage.transaction() as conn:
            owners = [
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT u.id FROM app.users u "
                    "JOIN app.user_emails e ON e.user_id=u.id "
                    "WHERE e.email_key=ANY(%s) AND e.is_primary",
                    ([FIXTURE_EMAIL, GOOGLE_EMAIL],),
                ).fetchall()
            ]
            counts = {}
            for table in (
                "context_notes",
                "chats",
                "messages",
                "analysis_requests",
                "analysis_jobs",
            ):
                query = "SELECT count(*) FROM app." + table + " WHERE user_id=ANY(%s)"
                if table == "context_notes":
                    query += " AND deleted_at IS NULL"
                counts[table] = conn.execute(query, (owners,)).fetchone()[0]
        return {
            "id": identifier,
            "kind": "notes_stats",
            "state": self.state,
            "notes": counts["context_notes"],
            "chats": counts["chats"],
            "messages": counts["messages"],
            "analysis": counts["analysis_requests"] + counts["analysis_jobs"],
            "engine_calls": self.engine.calls,
            "enqueue_calls": self.enqueue_calls,
            "provider_calls": self.provider_calls,
            "forbidden_requests": self.forbidden_requests,
        }

    def dispatch(self, item, client, service, deliver, captured, analysis=None):
        from p05_browser_messages import dispatch, forward_request

        identifier = item.get("id")
        if (
            type(identifier) not in {int, str}
            or type(identifier) is int
            and not 1 <= identifier <= 1000000
            or type(identifier) is str
            and (
                not 0 < len(identifier) <= 64
                or any(ord(value) < 32 or ord(value) == 127 for value in identifier)
            )
        ):
            raise ValueError("fixture_notes_identifier_invalid")
        kind = item.get("kind")
        if kind in {
            "notes_grant",
            "notes_revoke",
            "notes_regrant",
            "notes_history_advance",
            "notes_stats",
        }:
            return self.control(item)
        if kind == "mailbox":
            if (
                set(item) != {"id", "kind", "purpose"}
                or item["purpose"] != "verify_email"
                or self.mail_reads != 0
            ):
                raise ValueError("fixture_notes_mailbox_invalid")
            self.mail_reads += 1
            return dispatch(item, client, service, deliver, captured)
        if (
            kind != "request"
            or set(item) != {"id", "kind", "path", "method", "headers", "bodyBase64"}
            or not notes_route(item.get("path"), item.get("method"))
        ):
            self.forbidden_requests += 1
            raise ValueError("fixture_notes_request_forbidden")
        return forward_request(item, client, notes_route)
