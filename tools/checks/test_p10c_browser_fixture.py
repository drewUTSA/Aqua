"""Offline strict identity-fixture contracts; every DB/process/provider is fake."""

import base64
from contextlib import nullcontext
import inspect
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import p05_browser_host as host
from p05_browser_protocol import fixture_schema
import p05_browser_worker as worker
from p06_browser_routes import workspace_route
import p10c_browser_backend as entry
import p10c_browser_fixture as fixture

ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SESSION = "v2." + "s" * 43
BINDING = "v2." + "b" * 43
SECRET = "v2." + "c" * 43
IMAGE = "sha256:" + "b" * 64


class IdentityFixtureTests(unittest.TestCase):
    def make(self):
        conn = Mock()
        conn.execute.return_value.fetchone.return_value = (ID,)
        service = Mock()
        service.transaction.return_value = nullcontext(conn)
        settings = SimpleNamespace(
            app_origin=fixture.ORIGIN,
            session_secret="synthetic-session-secret",
            google_client_id="p05-fixture-client.apps.googleusercontent.com",
        )
        analysis = SimpleNamespace(max_executions=12)
        value = fixture.IdentityFixture(service, settings, analysis)
        value.cookies = {
            "__Host-aqua_session": SESSION,
            "__Host-aqua_account_action": BINDING,
            "__Host-aqua_identity_action": BINDING,
        }
        return value, conn, service, analysis

    def challenge(self, value, kind="reauth"):
        context = fixture.Challenge(
            kind,
            ID,
            fixture.digest(SECRET),
            fixture.digest(BINDING),
            fixture.digest(SESSION),
        )
        nonce = fixture.bound(
            value.settings,
            SECRET,
            "account-google-link-nonce" if kind == "link" else "account-google-nonce",
        )
        value.challenges[nonce] = context
        return nonce, context

    def item(self, value, nonce, identity="owner"):
        return {
            "id": 1,
            "kind": "google_assertion",
            "nonce": nonce,
            "client_id": value.settings.google_client_id,
            "identity": identity,
        }

    def test_schema_is_one_literal_not_an_eval_or_backend_import(self):
        root, target = Mock(), Mock()
        root.__truediv__ = Mock(return_value=target)
        target.is_symlink.return_value = False
        target.is_file.return_value = True
        target.stat.return_value.st_size = 32
        for schema in (6, 7, 8):
            target.read_text.return_value = f"SCHEMA_VERSION = {schema}\n"
            self.assertEqual(fixture_schema(root), schema)
        for text in (
            "SCHEMA_VERSION = 9",
            "SCHEMA_VERSION = True",
            "SCHEMA_VERSION = 7.0",
            "SCHEMA_VERSION = int('7')",
            "SCHEMA_VERSION: int = 7",
            "SCHEMA_VERSION = 7\nSCHEMA_VERSION = 6",
            "OTHER = 7",
            "SCHEMA_VERSION = 7\nSCHEMA_VERSION: int = 6",
            "SCHEMA_VERSION = 7\nSCHEMA_VERSION += 1",
            "SCHEMA_VERSION = OTHER = 7",
            "if True:\n SCHEMA_VERSION = 7",
        ):
            target.read_text.return_value = text
            with self.subTest(text=text), self.assertRaises(ValueError):
                fixture_schema(root)
        target.is_symlink.return_value = True
        with self.assertRaises(ValueError):
            fixture_schema(root)

    def test_dedicated_entry_origin_and_image_are_closed(self):
        self.assertEqual(entry.immutable_image(IMAGE), IMAGE)
        for image in (
            "aqua-runtime:check",
            "sha256:" + "B" * 64,
            "sha256:" + "b" * 63,
            None,
        ):
            with self.assertRaises(ValueError):
                entry.immutable_image(image)
        for origin in (
            "https://aqua-ai.us",
            fixture.ORIGIN + "/",
            fixture.ORIGIN + ":443",
            "http://127.0.0.1:5000",
        ):
            with self.assertRaises(ValueError):
                fixture.IdentityFixture(None, SimpleNamespace(app_origin=origin), None)

    def test_identity_mode_is_keyword_only_false_by_default(self):
        for function in (host.host, worker.worker):
            mode = inspect.signature(function).parameters["account_identity_fixture"]
            self.assertIs(mode.default, False)
            self.assertEqual(mode.kind, inspect.Parameter.KEYWORD_ONLY)
        with patch.object(host, "Resources") as resources:
            for value in (1, "true"):
                with self.assertRaises(ValueError):
                    host.host(
                        fixture.ORIGIN, IMAGE, True, account_identity_fixture=value
                    )
            with self.assertRaises(ValueError):
                host.host(fixture.ORIGIN, IMAGE, True, account_identity_fixture=True)
            resources.assert_not_called()

    def test_prior_adapters_gain_only_the_exact_notification_read(self):
        self.assertTrue(workspace_route("/api/v1/me/notification-settings", "GET"))
        for path, method in (
            ("/api/v1/me/notification-settings", "PUT"),
            ("/api/v1/me/notification-settings?owner_id=forged", "GET"),
            ("/api/v1/me/reauth/google", "POST"),
            ("/api/v1/me/email", "PUT"),
        ):
            self.assertFalse(workspace_route(path, method))

    def test_identity_routes_are_finite_without_alias_query_or_authority_rewrites(self):
        for path, methods in fixture.NEW_ROUTES.items():
            for method in methods:
                self.assertTrue(fixture.identity_route(path, method))
                self.assertFalse(fixture.identity_route(path + "?owner=forged", method))
        self.assertTrue(
            fixture.identity_route("/api/v1/auth/bootstrap?action=login", "GET")
        )
        for path, method in (
            ("https://aqua-ai.us/api/v1/me/email", "PUT"),
            ("//attacker.invalid/api/v1/me/email", "PUT"),
            ("/api/v1/me/email#token=private", "PUT"),
            ("/api/v1/me/email/", "PUT"),
            ("/api/v1/me/%65mail", "PUT"),
            ("/api/query", "POST"),
            ("/api/query", "GET"),
            ("/api/v1/chats", "POST"),
            ("/api/v1/auth/bootstrap?action=login&action=registration", "GET"),
            ("/api/auth/config?nonce=forged", "GET"),
            ("/api/v1/me/methods/google/../revocations", "POST"),
        ):
            self.assertFalse(fixture.identity_route(path, method), path)

    def test_signed_in_home_catalog_reads_do_not_enable_mutations_or_aliases(self):
        for path in (
            "/api/v1/chats",
            "/api/v1/chats?limit=20",
            "/api/v1/projects",
            "/api/v1/projects?limit=20",
            "/api/v1/starter-prompts",
        ):
            with self.subTest(path=path):
                self.assertTrue(fixture.identity_route(path, "GET"))
        for path in ("/api/v1/chats", "/api/v1/projects", "/api/v1/starter-prompts"):
            for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
                with self.subTest(path=path, method=method):
                    self.assertFalse(fixture.identity_route(path, method))
            for suffix in ("/", "?owner_id=forged", "?limit=1&limit=2", "#private"):
                with self.subTest(path=path, suffix=suffix):
                    self.assertFalse(fixture.identity_route(path + suffix, "GET"))
        self.assertFalse(
            fixture.identity_route("/api/v1/starter-prompts?limit=1", "GET")
        )

    def test_assertions_require_real_tracked_provenance_and_fixed_client_identity(self):
        value, conn, _, _ = self.make()
        nonce, _ = self.challenge(value)
        valid = self.item(value, nonce)
        for change in (
            {"nonce": "x" * 43},
            {"client_id": "foreign-client"},
            {"identity": "arbitrary-subject"},
            {"claims": {"sub": "forged"}},
            {"iat": 0},
            {"nonce": nonce + "x"},
        ):
            with self.assertRaises(ValueError):
                value.assertion({**valid, **change})
        conn.execute.assert_not_called()
        issued = value.assertion(valid)
        self.assertEqual(
            set(issued),
            {"id", "kind", "credential", "synthetic", "real_google_sdk_calls"},
        )
        self.assertNotIn(nonce, issued["credential"])
        sql, parameters = conn.execute.call_args.args
        self.assertIn("c.consumed_at IS NULL", sql)
        self.assertIn("e.revision=c.account_google_identity_revision", sql)
        self.assertIn("s.token_digest=%s", sql)
        self.assertEqual(parameters[-2:], fixture.OWNER)
        with self.assertRaises(ValueError):
            value.assertion(valid)

    def test_google_verifier_is_one_use_fixed_claims_and_fresh(self):
        value, conn, _, analysis = self.make()
        nonce, _ = self.challenge(value)
        issued = value.assertion(self.item(value, nonce))
        claims = value.verify(issued["credential"], value.settings.google_client_id)
        self.assertEqual((claims["sub"], claims["email"]), fixture.OWNER)
        self.assertEqual(claims["nonce"], nonce)
        self.assertEqual(claims["aud"], value.settings.google_client_id)
        self.assertIs(type(claims["iat"]), int)
        self.assertEqual(claims["exp"] - claims["iat"], 300)
        self.assertIn("c.consumed_at IS NOT NULL", conn.execute.call_args.args[0])
        self.assertEqual(analysis.max_executions, 0)
        self.assertEqual(value.metadata()["real_google_sdk_calls"], 0)
        with self.assertRaises(ValueError):
            value.verify(issued["credential"], value.settings.google_client_id)
        with self.assertRaises(ValueError):
            value.verify(json.dumps({"nonce": nonce}), value.settings.google_client_id)

    def test_candidate_assertion_is_one_predefined_identity_not_arbitrary_claims(self):
        value, _, _, _ = self.make()
        nonce, _ = self.challenge(value, "link")
        issued = value.assertion(self.item(value, nonce, "candidate"))
        claims = value.verify(issued["credential"], value.settings.google_client_id)
        self.assertEqual((claims["sub"], claims["email"]), fixture.CANDIDATE)
        self.assertNotIn("hd", claims)

    def test_owner_and_cookie_binding_changes_fence_and_burn_assertions(self):
        for change in ("session", "binding", "row"):
            value, conn, _, _ = self.make()
            nonce, _ = self.challenge(value)
            issued = value.assertion(self.item(value, nonce))
            if change == "session":
                value.cookies["__Host-aqua_session"] = "v2." + "t" * 43
            elif change == "binding":
                value.cookies["__Host-aqua_account_action"] = "v2." + "t" * 43
            else:
                conn.execute.return_value.fetchone.return_value = None
            with self.assertRaises(ValueError):
                value.verify(issued["credential"], value.settings.google_client_id)
            self.assertNotIn(issued["credential"], value.assertions)

    def test_google_assertion_memory_and_execution_count_are_bounded(self):
        value, _, _, _ = self.make()
        for index in range(fixture.MAX_ASSERTIONS):
            nonce = chr(ord("a") + index) * 43
            _, context = self.challenge(value)
            value.challenges[nonce] = context
            value.assertion(self.item(value, nonce))
        nonce = "z" * 43
        _, context = self.challenge(value)
        value.challenges[nonce] = context
        with self.assertRaises(ValueError):
            value.assertion(self.item(value, nonce))

    def test_tracking_accepts_only_real_bound_public_nonce_responses(self):
        value, _, _, _ = self.make()
        nonce = fixture.bound(value.settings, SECRET, "account-google-nonce")
        body = {
            "challenge_id": ID,
            "challenge_token": SECRET,
            "client_id": value.settings.google_client_id,
            "nonce": nonce,
        }
        result = {
            "status": 200,
            "headers": [
                [
                    "set-cookie",
                    "__Host-aqua_account_action="
                    + BINDING
                    + "; Path=/; Secure; HttpOnly",
                ]
            ],
            "bodyBase64": base64.b64encode(json.dumps(body).encode()).decode(),
        }
        value.track({"path": "/api/v1/me/reauth/google-challenges"}, result)
        self.assertIn(nonce, value.challenges)
        changed = {**body, "nonce": "x" * 43}
        result["bodyBase64"] = base64.b64encode(json.dumps(changed).encode()).decode()
        with self.assertRaises(ValueError):
            value.track({"path": "/api/v1/me/reauth/google-challenges"}, result)

    def test_login_assertion_requires_issued_csrf_bound_row_then_actual_consumption(
        self,
    ):
        value, conn, _, _ = self.make()
        value.cookies.clear()
        nonce = fixture.bound(value.settings, SECRET, "google-nonce")
        csrf = fixture.bound(value.settings, SECRET, "login-csrf")
        body = {
            "client_id": value.settings.google_client_id,
            "nonce": nonce,
            "csrf_token": csrf,
        }
        result = {
            "status": 200,
            "headers": [
                [
                    "set-cookie",
                    "__Host-aqua_login=" + SECRET + "; Path=/; Secure; HttpOnly",
                ]
            ],
            "bodyBase64": base64.b64encode(json.dumps(body).encode()).decode(),
        }
        value.track({"path": "/api/auth/config"}, result)
        self.assertIsNone(value.challenges[nonce].session)
        issued = value.assertion(self.item(value, nonce))
        self.assertIn("purpose='google_login'", conn.execute.call_args.args[0])
        self.assertIn("consumed_at IS NULL", conn.execute.call_args.args[0])
        self.assertEqual(
            conn.execute.call_args.args[1],
            (fixture.digest(SECRET), fixture.digest(csrf)),
        )
        value.verify(issued["credential"], value.settings.google_client_id)
        self.assertIn("consumed_at IS NOT NULL", conn.execute.call_args.args[0])
        for changed in (
            {**body, "csrf_token": "forged"},
            {**body, "client_id": "foreign"},
        ):
            result["bodyBase64"] = base64.b64encode(
                json.dumps(changed).encode()
            ).decode()
            with self.assertRaises(ValueError):
                value.track({"path": "/api/auth/config"}, result)

    def test_link_candidate_requires_claimed_phase_without_verified_or_consumed_request(
        self,
    ):
        value, conn, _, _ = self.make()
        nonce, _ = self.challenge(value, "link")
        issued = value.assertion(self.item(value, nonce, "candidate"))
        sql, parameters = conn.execute.call_args.args
        self.assertIn("r.claimed_at IS NULL", sql)
        self.assertIn("r.verified_at IS NULL", sql)
        self.assertIn("r.consumed_at IS NULL", sql)
        self.assertEqual(parameters[:2], (ID, "google_link"))
        value.verify(issued["credential"], value.settings.google_client_id)
        self.assertIn("r.claimed_at IS NOT NULL", conn.execute.call_args.args[0])
        self.assertIn(
            "u.email_revision=r.source_email_revision", conn.execute.call_args.args[0]
        )

    def test_mail_request_tracking_requires_current_session_cookie_and_canonical_id(
        self,
    ):
        value, _, _, _ = self.make()
        body = {"request_id": ID, "request_token": SECRET}

        def result(changed):
            return {
                "status": 200,
                "headers": [],
                "bodyBase64": base64.b64encode(json.dumps(changed).encode()).decode(),
            }

        value.track({"path": "/api/v1/me/password-enrollments"}, result(body))
        self.assertEqual(value.requests[ID].kind, "password_add")
        for changed in (
            {**body, "request_id": ID.upper()},
            {**body, "request_token": None},
            [],
        ):
            with self.assertRaises(ValueError):
                value.track(
                    {"path": "/api/v1/me/password-enrollments"}, result(changed)
                )
        value.cookies.pop("__Host-aqua_session")
        with self.assertRaises(ValueError):
            value.track({"path": "/api/v1/me/email-change-requests"}, result(body))

    def test_control_surface_has_no_clock_grants_jobs_queries_or_notice_body(self):
        value, conn, service, analysis = self.make()
        deliver = Mock()
        for kind in (
            "recover_rates",
            "workspace_grant",
            "workspace_revoke",
            "workspace_release",
            "workspace_restart",
            "workspace_recover_analysis_rate",
            "notice_body",
            "claims",
            "seed",
            "mailbox",
        ):
            with self.assertRaises(ValueError):
                value.dispatch(
                    {"id": 1, "kind": kind}, None, service, deliver, [], analysis
                )
        with self.assertRaises(ValueError):
            value.dispatch(
                {"id": 1, "kind": "mailbox", "purpose": "password_changed"},
                None,
                service,
                deliver,
                [],
                analysis,
            )
        conn.execute.assert_not_called()
        deliver.assert_not_called()

    def test_new_mailbox_requires_exact_owned_request_and_never_returns_payload(self):
        value, conn, service, analysis = self.make()
        context = fixture.Challenge(
            "email_change",
            ID,
            fixture.digest(SECRET),
            fixture.digest(BINDING),
            fixture.digest(SESSION),
        )
        value.requests[ID] = context
        token = "m" * 43
        link = (
            fixture.ORIGIN
            + "/account-action/email_change_new#request="
            + ID
            + "&token="
            + token
        )
        captured = [
            {
                "purpose": "email_change_new",
                "request_id": ID,
                "to": fixture.NEW_EMAIL,
                "subject": "synthetic private subject",
                "text": link + "\n",
                "html": "private body",
            }
        ]
        item = {
            "id": 1,
            "kind": "identity_mailbox",
            "purpose": "email_change_new",
            "request_id": ID,
        }
        with patch.dict(
            "sys.modules",
            {"auth.mailpurposes": SimpleNamespace(ACCOUNT_MAIL_SQL="TRUE")},
        ):
            result = value.dispatch(item, None, service, Mock(), captured, analysis)
        self.assertTrue(result["found"])
        self.assertEqual(result["link"], link)
        self.assertEqual(result["proof"], token)
        self.assertIn("c.target_email_key=%s", conn.execute.call_args.args[0])
        self.assertEqual(
            conn.execute.call_args.args[1],
            (ID, "email_change_new", fixture.NEW_EMAIL, fixture.digest(token)),
        )
        self.assertNotIn("payload", result)
        self.assertNotIn("private", json.dumps(result))
        self.assertFalse(result["body_exposed"])
        self.assertEqual(captured, [])

    def test_mailbox_rejects_foreign_recipient_and_expired_proof_and_bounds_polling(
        self,
    ):
        value, conn, _, _ = self.make()
        value.requests[ID] = fixture.Challenge(
            "email_change",
            ID,
            fixture.digest(SECRET),
            fixture.digest(BINDING),
            fixture.digest(SESSION),
        )
        item = {
            "id": 1,
            "kind": "identity_mailbox",
            "purpose": "email_change_new",
            "request_id": ID,
        }
        link = (
            fixture.ORIGIN
            + "/account-action/email_change_new#request="
            + ID
            + "&token="
            + "m" * 43
        )
        payload = {
            "purpose": "email_change_new",
            "request_id": ID,
            "to": "foreign@example.test",
            "text": link,
        }
        deliver = Mock()
        with self.assertRaises(ValueError):
            value.mailbox(item, deliver, [payload])
        deliver.assert_not_called()
        payload["to"] = fixture.NEW_EMAIL
        conn.execute.return_value.fetchone.side_effect = [(ID,), None]
        with (
            patch.dict(
                "sys.modules",
                {"auth.mailpurposes": SimpleNamespace(ACCOUNT_MAIL_SQL="TRUE")},
            ),
            self.assertRaises(ValueError),
        ):
            value.mailbox(item, deliver, [payload])
        deliver.assert_not_called()
        conn.execute.return_value.fetchone.side_effect = None
        conn.execute.return_value.fetchone.return_value = (ID,)
        with patch.object(fixture.time, "sleep") as sleep:
            missing = value.mailbox(item, deliver, [])
        self.assertFalse(missing["found"])
        self.assertEqual(deliver.call_count, 8)
        self.assertEqual(sleep.call_count, 8)

    def test_stale_foreign_or_notice_mailbox_request_is_denied_before_delivery(self):
        for change in ("foreign", "notice", "extra", "binding"):
            value, _, service, analysis = self.make()
            value.requests[ID] = fixture.Challenge(
                "email_change",
                ID,
                fixture.digest(SECRET),
                fixture.digest(BINDING),
                fixture.digest(SESSION),
            )
            item = {
                "id": 1,
                "kind": "identity_mailbox",
                "purpose": "email_change_old",
                "request_id": ID,
            }
            if change == "foreign":
                item["request_id"] = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
            elif change == "notice":
                item["purpose"] = "email_changed"
            elif change == "extra":
                item["owner_id"] = ID
            else:
                value.cookies["__Host-aqua_identity_action"] = "v2." + "t" * 43
            deliver = Mock()
            with self.assertRaises(ValueError):
                value.dispatch(item, None, service, deliver, [], analysis)
            deliver.assert_not_called()

    def test_notice_status_is_only_finite_counts_and_no_secret_body(self):
        value, conn, service, analysis = self.make()
        conn.execute.return_value.fetchall.return_value = [
            ("email_changed", "sent", 2),
            ("google_linked", "pending", 1),
        ]
        result = value.dispatch(
            {"id": 1, "kind": "identity_mail_status"}, None, service, None, [], analysis
        )
        self.assertEqual(result["purposes"]["email_changed"]["completed"], 2)
        self.assertEqual(result["purposes"]["google_linked"]["queued"], 1)
        self.assertEqual(
            set(result),
            {"id", "kind", "purposes", "body_exposed", "real_provider_calls"},
        )
        self.assertNotIn("token", json.dumps(result))
        for bad in [
            ("email_changed", "sent", True),
            ("foreign", "sent", 1),
            ("email_changed", "sent", 4097),
        ]:
            conn.execute.return_value.fetchall.return_value = [bad]
            with self.assertRaises(ValueError):
                value.notice_status({"id": 1, "kind": "identity_mail_status"})

    def test_http_forwarding_preserves_real_cookie_origin_csrf_and_closes_cookie_jar(
        self,
    ):
        value, _, service, analysis = self.make()
        response = SimpleNamespace(
            status_code=200,
            content=b"{}",
            headers=SimpleNamespace(multi_items=lambda: []),
        )
        client = Mock()
        client.request.return_value = response
        headers = [
            ["Origin", fixture.ORIGIN],
            ["Cookie", "__Host-aqua_session=" + SESSION],
            ["X-CSRF-Token", "synthetic-current"],
        ]
        item = {
            "id": 1,
            "kind": "request",
            "path": "/api/v1/me/notification-settings",
            "method": "PUT",
            "headers": headers,
            "bodyBase64": base64.b64encode(b'{"expectedRevision":1}').decode(),
        }
        value.dispatch(item, client, service, None, [], analysis)
        self.assertEqual(
            client.request.call_args.kwargs["headers"],
            [tuple(pair) for pair in headers],
        )
        self.assertFalse(client.request.call_args.kwargs["follow_redirects"])
        self.assertEqual(client.cookies.clear.call_count, 2)

    def test_invalid_forwarding_never_reaches_client(self):
        value, _, service, analysis = self.make()
        client = Mock()
        base = {"id": 1, "kind": "request", "path": "/api/v1/me/email", "method": "PUT"}
        for change in (
            {"headers": [["Origin", "https://outside.invalid\nforged"]]},
            {"headers": [["Cookie", "one"], ["Cookie", "two"]]},
            {"bodyBase64": base64.b64encode(b"x" * (16384 + 1)).decode()},
            {"path": "/api/query", "method": "POST"},
            {"claims": {}},
        ):
            with self.assertRaises(ValueError):
                value.dispatch({**base, **change}, client, service, None, [], analysis)
        client.request.assert_not_called()

    def host_case(self, ready, remaining=None, identity=True):
        child = SimpleNamespace(
            stdin=Mock(),
            stdout=io.BytesIO(json.dumps(ready).encode() + b"\n"),
            wait=Mock(return_value=0),
            terminate=Mock(),
            kill=Mock(),
        )
        resources = Mock()
        resources.provision.return_value = "a" * 64
        resources.cleanup.return_value = remaining or []
        with (
            patch.object(host, "Resources", return_value=resources),
            patch.object(host.subprocess, "Popen", return_value=child) as launch,
            patch.object(
                host, "message", return_value={"id": "finish", "kind": "finish"}
            ),
            patch.object(host, "emit") as emit,
            patch.multiple(
                host.signal,
                SIGALRM=14,
                SIGHUP=1,
                signal=Mock(),
                alarm=Mock(),
                create=True,
            ),
        ):
            result = host.host(
                fixture.ORIGIN,
                IMAGE,
                True,
                account_security_fixture=True,
                account_identity_fixture=identity,
            )
        return result, launch, resources, emit

    def test_host_selects_only_dedicated_c_worker_and_preserves_caps_cleanup(self):
        result, launch, resources, emit = self.host_case(
            {
                "kind": "ready",
                "schema_version": fixture_schema(host.ROOT),
                "account_security_fixture": True,
                "account_identity_fixture": True,
            }
        )
        self.assertEqual(result, 0)
        command = launch.call_args.args[0]
        self.assertIn("/checks/tools/checks/p10c_browser_backend.py", command)
        self.assertEqual(command[-4:], ["--origin", fixture.ORIGIN, "--image", IMAGE])
        self.assertEqual(emit.call_args.args[0]["report"]["max_operations"], 300)
        self.assertEqual(host.MAX_SECONDS, 300)
        resources.cleanup.assert_called_once()

    def test_wrong_marker_schema_or_remaining_resource_cannot_pass(self):
        for ready in (
            {
                "kind": "ready",
                "schema_version": 6,
                "account_security_fixture": True,
                "account_identity_fixture": True,
            },
            {
                "kind": "ready",
                "schema_version": fixture_schema(host.ROOT),
                "account_security_fixture": True,
            },
        ):
            result, _, resources, _ = self.host_case(ready)
            self.assertEqual(result, 1)
            resources.cleanup.assert_called_once()
        result, _, _, emitted = self.host_case(
            {
                "kind": "ready",
                "schema_version": fixture_schema(host.ROOT),
                "account_security_fixture": True,
                "account_identity_fixture": True,
            },
            ["owned-still-present"],
        )
        self.assertEqual(result, 1)
        self.assertEqual(
            emitted.call_args.args[0]["report"]["remaining_ids"],
            ["owned-still-present"],
        )

    def test_identity_worker_cannot_masquerade_as_default_security_worker(self):
        result, _, resources, emitted = self.host_case(
            {
                "kind": "ready",
                "schema_version": fixture_schema(host.ROOT),
                "account_security_fixture": True,
                "account_identity_fixture": True,
            },
            identity=False,
        )
        self.assertEqual(result, 1)
        self.assertEqual(emitted.call_args.args[0]["status"], "failed")
        resources.cleanup.assert_called_once()

    def test_identity_clear_discards_transient_cookies_requests_and_assertions(self):
        value, _, _, _ = self.make()
        nonce, context = self.challenge(value)
        value.requests[ID] = context
        value.assertion(self.item(value, nonce))
        value.clear()
        self.assertEqual(
            (value.cookies, value.challenges, value.requests, value.assertions),
            ({}, {}, {}, {}),
        )


if __name__ == "__main__":
    unittest.main()
