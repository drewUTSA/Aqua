"""Offline secure fixture boundaries; no Docker, socket, application or provider."""

import base64
from contextlib import nullcontext
import inspect
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import p05_browser_host as bridge
import p05_browser_worker as worker
import p10b_browser_fixture as fixture

IMAGE = "sha256:" + "b" * 64


class SecurityFixtureTests(unittest.TestCase):
    def test_secure_origin_is_one_reserved_host_not_a_network_target(self) -> None:
        self.assertEqual(
            fixture.secure_origin("https://aqua-browser.example.test"), fixture.ORIGIN
        )
        for origin in [
            "https://aqua-ai.us",
            "http://aqua-browser.example.test",
            "https://127.0.0.1:5000",
            "http://127.0.0.1:5000",
            fixture.ORIGIN + "/",
            fixture.ORIGIN + ":443",
            fixture.ORIGIN + "?a=1",
            "https://person@aqua-browser.example.test",
            "https://aqua-browser.example.test.attacker.invalid",
            None,
        ]:
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                fixture.secure_origin(origin)

    def test_mail_environment_is_exact_origin_and_fake_encryption_key_only(
        self,
    ) -> None:
        result = fixture.mail_environment(fixture.ORIGIN, b"s" * 32)
        self.assertEqual(
            set(result),
            {
                "ACCOUNT_MAIL_ENABLED",
                "ACCOUNT_PUBLIC_ORIGIN",
                "ACCOUNT_MAIL_OUTBOX_KEY",
            },
        )
        self.assertEqual(result["ACCOUNT_PUBLIC_ORIGIN"], fixture.ORIGIN)
        self.assertEqual(
            base64.urlsafe_b64decode(result["ACCOUNT_MAIL_OUTBOX_KEY"]), b"s" * 32
        )
        self.assertEqual(result["ACCOUNT_MAIL_ENABLED"], "true")
        for key in [b"s" * 31, "s" * 32, None]:
            with self.assertRaises(ValueError):
                fixture.mail_environment(fixture.ORIGIN, key)

    def test_quota_clock_grant_job_controls_and_notice_body_are_closed(self) -> None:
        service, client, delivery = Mock(), Mock(), Mock()
        for kind in [
            "recover_rates",
            "workspace_grant",
            "workspace_revoke",
            "workspace_release",
            "workspace_restart",
            "workspace_recover_analysis_rate",
        ]:
            with self.assertRaises(ValueError):
                fixture.security_dispatch(
                    {"id": 1, "kind": kind}, client, service, delivery, [], None
                )
        with self.assertRaises(ValueError):
            fixture.security_dispatch(
                {"id": 1, "kind": "mailbox", "purpose": "password_changed"},
                client,
                service,
                delivery,
                [],
                None,
            )
        for path in [
            "/api/query",
            "/api/v1/chats",
            "/api/v1/chats/id/messages",
            "/api/v1/chats/id/messages/id/retries",
        ]:
            with self.assertRaises(ValueError):
                fixture.security_dispatch(
                    {"id": 1, "kind": "request", "method": "POST", "path": path},
                    client,
                    service,
                    delivery,
                    [],
                    None,
                )
        service.assert_not_called()
        self.assertEqual(service.mock_calls, [])
        delivery.assert_not_called()
        client.assert_not_called()

    def test_notice_status_returns_only_fixed_purpose_and_bounded_counters(
        self,
    ) -> None:
        connection = Mock()
        connection.execute.return_value.fetchall.return_value = [
            ("pending", 1),
            ("sent", 2),
        ]
        service = Mock()
        service.transaction.return_value = nullcontext(connection)
        result = fixture.security_dispatch(
            {"id": 1, "kind": "security_mail_status"}, None, service, None, [], None
        )
        self.assertEqual(
            result,
            {
                "id": 1,
                "kind": "security_mail_status",
                "purpose": "password_changed",
                "queued": 1,
                "completed": 2,
                "failed": 0,
                "body_exposed": False,
                "real_provider_calls": 0,
            },
        )
        self.assertNotIn("token", json.dumps(result))
        with self.assertRaises(ValueError):
            fixture.security_dispatch(
                {"id": 1, "kind": "security_mail_status", "owner_id": "forged"},
                None,
                service,
                None,
                [],
                None,
            )
        self.assertEqual(service.transaction.call_count, 1)

    def test_forwarding_never_rewrites_cookie_origin_or_csrf_authority(self) -> None:
        item = {
            "id": 1,
            "kind": "request",
            "method": "POST",
            "path": "/api/v1/me/reauth-challenges",
            "headers": [
                ["Origin", fixture.ORIGIN],
                ["Cookie", "synthetic"],
                ["X-CSRF-Token", "bound"],
            ],
        }
        with patch.object(fixture, "dispatch", return_value={"id": 1}) as forward:
            self.assertEqual(
                fixture.security_dispatch(
                    item, "client", "service", "delivery", [], "analysis"
                ),
                {"id": 1},
            )
        self.assertIs(forward.call_args.args[0], item)

    def test_worker_seam_is_keyword_only_default_closed(self) -> None:
        mode = inspect.signature(worker.worker).parameters["account_security_fixture"]
        self.assertIs(mode.default, False)
        self.assertEqual(mode.kind, inspect.Parameter.KEYWORD_ONLY)

    def host(self, ready: dict) -> tuple[int, Mock, Mock]:
        child = SimpleNamespace(
            stdin=Mock(),
            stdout=io.BytesIO(json.dumps(ready).encode() + b"\n"),
            wait=Mock(return_value=0),
            terminate=Mock(),
            kill=Mock(),
        )
        resources = Mock()
        resources.provision.return_value = "a" * 64
        resources.cleanup.return_value = []
        with (
            patch.object(bridge, "Resources", return_value=resources),
            patch.object(bridge.subprocess, "Popen", return_value=child) as launch,
            patch.object(
                bridge, "message", return_value={"id": "finish", "kind": "finish"}
            ),
            patch.object(bridge, "emit"),
            patch.multiple(
                bridge.signal,
                SIGALRM=14,
                SIGHUP=1,
                signal=Mock(),
                alarm=Mock(),
                create=True,
            ),
        ):
            result = bridge.host(
                fixture.ORIGIN, IMAGE, True, account_security_fixture=True
            )
        return result, launch, resources

    def test_host_pins_dedicated_worker_image_and_confirms_cleanup(self) -> None:
        result, launch, resources = self.host(
            {
                "kind": "ready",
                "schema_version": bridge.fixture_schema(bridge.ROOT),
                "account_security_fixture": True,
            }
        )
        self.assertEqual(result, 0)
        command = launch.call_args.args[0]
        self.assertIn("/checks/tools/checks/p10b_browser_backend.py", command)
        self.assertNotIn("/checks/tools/checks/p05_browser_backend.py", command)
        self.assertEqual(command[-4:], ["--origin", fixture.ORIGIN, "--image", IMAGE])
        resources.cleanup.assert_called_once()
        self.assertEqual(bridge.MAX_SECONDS, 300)
        self.assertEqual(fixture.MAX_REQUESTS, 300)

    def test_wrong_fixture_ready_marker_cannot_pass_but_cleanup_runs(self) -> None:
        result, _, resources = self.host(
            {"kind": "ready", "schema_version": bridge.fixture_schema(bridge.ROOT)}
        )
        self.assertEqual(result, 1)
        resources.cleanup.assert_called_once()


if __name__ == "__main__":
    unittest.main()
