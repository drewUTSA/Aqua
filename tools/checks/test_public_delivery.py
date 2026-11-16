"""Offline delivery-check tests; every response and clock is a fake."""

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_public_delivery as check  # noqa: E402
import public_delivery_transport as wire  # noqa: E402


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class Response:
    def __init__(self, body=b"", *, status=200, headers=None, clock=None, delay=0):
        self.body = body
        self.status = status
        self.headers = headers or [("Content-Type", "text/html")]
        self.clock = clock
        self.delay = delay
        self.closed = False
        self.read_sizes = []

    def read(self, size, timeout):
        self.read_sizes.append(size)
        if self.clock:
            self.clock.value += self.delay
        value, self.body = self.body[:size], self.body[size:]
        return value

    def close(self):
        self.closed = True


class Transport:
    def __init__(self, replies=None, *, clock=None, delay=0):
        self.replies = replies or {}
        self.clock = clock
        self.delay = delay
        self.calls = []
        self.responses = []

    def open(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.clock:
            self.clock.value += self.delay
        path = wire.urlsplit(url).path
        value = self.replies.get(
            path, lambda: Response(b"<!doctype html><html>app</html>")
        )
        if isinstance(value, Exception):
            raise value
        response = value()
        self.responses.append(response)
        return response


def find(result, path):
    return next(item for item in result["checks"] if item["path"] == path)


class DeliveryTests(unittest.TestCase):
    def test_fixed_gets_have_no_authentication_or_cookie_reuse(self):
        transport = Transport(
            {"/": lambda: Response(headers=[("Set-Cookie", "secret=COOKIE_SENTINEL")])}
        )
        result = check.inspect(check.ORIGINS[0], transport)
        self.assertTrue(result["inspection_complete"])
        self.assertEqual(result["network_requests"], 7)
        self.assertFalse(result["p13_launch_complete"])
        for url, arguments in transport.calls:
            self.assertTrue(check.fixed_url(url, check.ORIGINS[0]))
            self.assertEqual(arguments["method"], "GET")
            self.assertEqual(arguments["headers"], check.REQUEST_HEADERS)
            self.assertFalse(
                {"authorization", "cookie", "proxy-authorization"}
                & {name.lower() for name in arguments["headers"]}
            )
        self.assertTrue(all(response.closed for response in transport.responses))
        self.assertNotIn("COOKIE_SENTINEL", json.dumps(result))

    def test_receipt_classifies_without_copying_any_response_values(self):
        sentinel = "PRIVATE_SENTINEL"
        headers = [
            ("Content-Type", "text/html; secret=" + sentinel),
            ("Content-Security-Policy", sentinel),
            ("Content-Security-Policy-Report-Only", sentinel),
            ("Strict-Transport-Security", "max-age=31536000; " + sentinel),
            ("Set-Cookie", sentinel),
            ("X-Frame-Options", sentinel),
            ("Referrer-Policy", sentinel),
        ]
        result = check.inspect(
            check.ORIGINS[0],
            Transport(
                {"/": lambda: Response(b"<html>" + sentinel.encode(), headers=headers)}
            ),
        )
        home = find(result, "/")
        self.assertTrue(home["csp_present"])
        self.assertTrue(home["hsts_max_age_positive"])
        self.assertEqual(home["frame_policy"], "other")
        self.assertNotIn(sentinel, json.dumps(result))
        self.assertNotIn("<html>", json.dumps(result))

    def test_discovery_spa_and_denial_observations_are_independent(self):
        replies = {
            "/api/ready": lambda: Response(
                b"{}", status=404, headers=[("content-type", "application/json")]
            ),
            "/api/v1/me": lambda: Response(
                b"{}", status=401, headers=[("content-type", "application/json")]
            ),
        }
        result = check.inspect(check.ORIGINS[0], Transport(replies))
        self.assertEqual(
            result["observations"],
            {
                "private_readiness_returns_404": True,
                "unauthenticated_profile_denied": True,
                "unknown_route_returns_404": False,
                "robots_serves_html": True,
                "sitemap_serves_html": True,
            },
        )
        self.assertFalse(find(result, "/")["csp_present"])
        self.assertFalse(find(result, "/")["hsts_present"])
        replies[check.PATHS[4]] = lambda: Response(status=404)
        replies["/robots.txt"] = lambda: Response(
            b"User-agent: *\nDisallow: /", headers=[("Content-Type", "text/plain")]
        )
        replies["/sitemap.xml"] = lambda: Response(
            b'<?xml version="1.0"?><urlset xmlns="urn:fake"></urlset>',
            headers=[("Content-Type", "application/xml")],
        )
        result = check.inspect(check.ORIGINS[0], Transport(replies))
        self.assertTrue(result["observations"]["unknown_route_returns_404"])
        self.assertTrue(find(result, "/robots.txt")["robots_directives_detected"])
        self.assertTrue(find(result, "/sitemap.xml")["sitemap_root_detected"])
        self.assertFalse(result["observations"]["robots_serves_html"])

    def test_redirects_cannot_leave_the_exact_origin_or_fixed_paths(self):
        for destination in (
            "https://example.com/SECRET",
            "http://aqua-ai.us/",
            "https://www.aqua-ai.us/",
            "https://user:SECRET@aqua-ai.us/",
            "/signin?token=SECRET",
            "/signin#SECRET",
            "/arbitrary",
            "https://aqua-ai.us:443/",
        ):
            with self.subTest(destination=destination):
                transport = Transport(
                    {
                        "/": lambda: Response(
                            status=302, headers=[("Location", destination)]
                        )
                    }
                )
                result = check.inspect(check.ORIGINS[0], transport)
                self.assertEqual(
                    find(result, "/")["error"], "redirect_destination_denied"
                )
                self.assertEqual(len(transport.calls), 7)
                self.assertNotIn("SECRET", json.dumps(result))
                self.assertTrue(
                    all(
                        check.fixed_url(url, check.ORIGINS[0])
                        for url, _ in transport.calls
                    )
                )

    def test_one_fixed_same_origin_redirect_uses_eighth_request(self):
        transport = Transport(
            {"/": lambda: Response(status=302, headers=[("location", "/signin")])}
        )
        result = check.inspect(check.ORIGINS[0], transport)
        self.assertTrue(result["inspection_complete"])
        self.assertEqual(result["network_requests"], 8)
        self.assertEqual(find(result, "/")["redirects_followed"], 1)

    def test_redirected_404_does_not_claim_true_unknown_route_404(self):
        transport = Transport(
            {
                check.PATHS[4]: lambda: Response(
                    status=302, headers=[("location", "/signin")]
                ),
                "/signin": lambda: Response(status=404),
            }
        )
        result = check.inspect(check.ORIGINS[0], transport)
        unknown = find(result, check.PATHS[4])
        self.assertEqual(unknown["initial_status"], 302)
        self.assertEqual(unknown["status"], 404)
        self.assertFalse(result["observations"]["unknown_route_returns_404"])

    def test_redirect_chains_and_request_budget_are_closed(self):
        replies = {
            "/": lambda: Response(status=302, headers=[("location", "/signin")]),
            "/signin": lambda: Response(
                status=302, headers=[("location", "/robots.txt")]
            ),
        }
        transport = Transport(replies)
        result = check.inspect(check.ORIGINS[0], transport)
        self.assertEqual(find(result, "/")["error"], "redirect_limit")
        self.assertLessEqual(len(transport.calls), 8)
        self.assertFalse(result["inspection_complete"])
        transport = Transport(
            {"/": lambda: Response(status=302, headers=[("location", "/")])}
        )
        self.assertEqual(
            find(check.inspect(check.ORIGINS[0], transport), "/")["error"],
            "redirect_loop",
        )

    def test_body_byte_cap_and_untrusted_length_and_encoding(self):
        cases = [
            (lambda: Response(b"x" * (check.BODY_BYTES + 1)), "body_budget"),
            (
                lambda: Response(
                    headers=[("Content-Length", str(check.BODY_BYTES + 1))]
                ),
                "body_budget",
            ),
            (
                lambda: Response(headers=[("Content-Length", "SECRET")]),
                "content_length_invalid",
            ),
            (
                lambda: Response(
                    headers=[("Content-Length", "1"), ("Content-Length", "2")]
                ),
                "content_length_invalid",
            ),
            (
                lambda: Response(headers=[("Content-Encoding", "gzip")]),
                "content_encoding_denied",
            ),
            (
                lambda: Response(b"x", headers=[("Content-Length", "2")]),
                "body_length_mismatch",
            ),
        ]
        for factory, category in cases:
            transport = Transport({"/": factory})
            result = check.inspect(check.ORIGINS[0], transport)
            self.assertEqual(find(result, "/")["error"], category)
            self.assertFalse(find(result, "/")["complete"])
            self.assertNotIn("SECRET", json.dumps(result))
            self.assertTrue(
                all(
                    size <= 8192
                    for response in transport.responses
                    for size in response.read_sizes
                )
            )

    def test_connect_read_and_total_deadlines_without_waiting(self):
        clock = Clock()
        result = check.inspect(
            check.ORIGINS[0], Transport(clock=clock, delay=4), clock=clock
        )
        self.assertEqual(find(result, "/")["error"], "connect_header_deadline")
        self.assertFalse(result["inspection_complete"])
        clock = Clock()
        result = check.inspect(
            check.ORIGINS[0],
            Transport({"/": lambda: Response(clock=clock, delay=3)}),
            clock=clock,
        )
        self.assertEqual(find(result, "/")["error"], "read_deadline")
        clock = Clock()
        result = check.inspect(
            check.ORIGINS[0], Transport(clock=clock, delay=21), clock=clock
        )
        self.assertEqual(find(result, "/")["error"], "total_deadline")
        self.assertEqual(result["network_requests"], 1)

    def test_raw_transport_errors_and_failed_observations_stay_sanitized(self):
        result = check.inspect(
            check.ORIGINS[0],
            Transport({"/api/v1/me": RuntimeError("SECRET Cookie: token")}),
        )
        self.assertEqual(find(result, "/api/v1/me")["error"], "transport_failure")
        self.assertIsNone(result["observations"]["unauthenticated_profile_denied"])
        self.assertNotIn("SECRET", json.dumps(result))

    def test_transport_itself_rejects_posts_or_extra_headers_before_connect(self):
        with mock.patch.object(wire.http.client, "HTTPSConnection") as connection:
            for method, url, headers in [
                ("POST", check.ORIGINS[0] + "/", check.REQUEST_HEADERS),
                ("GET", "https://example.com/", check.REQUEST_HEADERS),
                (
                    "GET",
                    check.ORIGINS[0] + "/",
                    {**check.REQUEST_HEADERS, "Cookie": "SECRET"},
                ),
            ]:
                with self.assertRaises(check.InspectionStopped):
                    check.PublicHTTPS().open(
                        url,
                        origin=check.ORIGINS[0],
                        method=method,
                        headers=headers,
                        timeout=1,
                    )
            connection.assert_not_called()

    def test_detached_response_socket_still_gets_read_timeout(self):
        sock = mock.Mock()
        response = SimpleNamespace(
            status=200,
            getheaders=lambda: [],
            fp=SimpleNamespace(raw=SimpleNamespace(_sock=sock)),
            read1=lambda size: b"",
        )
        wrapped = wire.HTTPResponse(SimpleNamespace(sock=None), response)
        self.assertEqual(wrapped.read(10, 1.25), b"")
        sock.settimeout.assert_called_once_with(1.25)
        response.fp = None
        self.assertEqual(wrapped.read(10, 1.25), b"")

    def test_dry_run_and_create_only_output_never_start_network(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(check, "live_inspection") as network,
        ):
            output = Path(directory) / "receipt.json"
            self.assertEqual(check.main(["--output", str(output)]), 0)
            self.assertEqual(
                json.loads(output.read_text())["mode"], "plan_only_no_network"
            )
            self.assertEqual(json.loads(output.read_text())["network_requests"], 0)
            with (
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                check.main(["--execute", "--output", str(output)])
            with (
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                check.main(["--origin", "https://example.com"])
            with (
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                check.main(["--_worker"])
            network.assert_not_called()

    def test_live_wrapper_uses_allowlisted_environment_and_hard_total_timeout(self):
        value = check.receipt(check.ORIGINS[0], "executed")
        with mock.patch.object(
            wire.subprocess,
            "run",
            return_value=SimpleNamespace(
                returncode=1, stdout=json.dumps(value).encode()
            ),
        ) as worker:
            check.live_inspection(check.ORIGINS[0])
            arguments = worker.call_args
            self.assertIn("--execute", arguments.args[0])
            self.assertEqual(arguments.kwargs["env"], wire.worker_environment())
            self.assertEqual(arguments.kwargs["timeout"], check.TOTAL_SECONDS)
            self.assertEqual(arguments.kwargs["stderr"], subprocess.DEVNULL)
        with mock.patch.object(
            wire.subprocess, "run", side_effect=subprocess.TimeoutExpired("hidden", 20)
        ):
            result = check.live_inspection(check.ORIGINS[0])
            self.assertEqual(result["error"], "hard_total_deadline")
            self.assertIsNone(result["network_requests"])
            self.assertFalse(result["inspection_complete"])

    def test_windows_worker_keeps_only_system_root_and_drops_credentials(self):
        environment = {
            "SystemRoot": "C:/Windows",
            "PATH": "SECRET_PATH",
            "HTTPS_PROXY": "SECRET_PROXY",
            "GEMINI_API_KEY": "SECRET_KEY",
            "SSL_CERT_FILE": "SECRET_CERT_OVERRIDE",
        }
        with mock.patch.dict(wire.os.environ, environment, clear=True):
            with mock.patch.object(wire.os, "name", "nt"):
                self.assertEqual(
                    wire.worker_environment(), {"SystemRoot": "C:/Windows"}
                )
            with mock.patch.object(wire.os, "name", "posix"):
                self.assertEqual(wire.worker_environment(), {})
        with mock.patch.dict(wire.os.environ, {}, clear=True):
            with mock.patch.object(wire.os, "name", "nt"):
                self.assertEqual(
                    wire.worker_environment(), {"SystemRoot": "C:/Windows"}
                )

    def test_isolated_script_can_import_helpers_without_network_opt_in(self):
        completed = subprocess.run(
            [sys.executable, "-I", "-B", str(Path(check.__file__).resolve())],
            capture_output=True,
            timeout=5,
            env={},
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        value = json.loads(completed.stdout)
        self.assertEqual(value["mode"], "plan_only_no_network")
        self.assertEqual(value["network_requests"], 0)


if __name__ == "__main__":
    unittest.main()
