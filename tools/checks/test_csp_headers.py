"""Document-only CSP must not change proxy authority or the nonce redirect."""

from pathlib import Path
import re
import unittest

import public_delivery_proxy_probe as probe

ROOT = Path(__file__).resolve().parents[2]


class Response:
    def __init__(self, headers):
        self.headers = headers

    def getheaders(self):
        return self.headers

    def getheader(self, name):
        return next(
            (value for key, value in self.headers if key.lower() == name.lower()), None
        )


class DocumentCsp(unittest.TestCase):
    def setUp(self):
        self.nginx = (ROOT / "frontend/nginx.conf").read_text()
        self.headers = re.findall(
            r'^\s*add_header (Content-Security-Policy(?:-Report-Only)?) "([^"\r\n]+)" always;',
            self.nginx,
            re.M,
        )

    def test_policies_are_document_only_and_no_transport_policy_is_activated(self):
        self.assertEqual(len(self.headers), 4)
        prefix = self.nginx.split("    # Restricted launch:")[0]
        self.assertNotIn("Content-Security-Policy", prefix)
        for name in (
            "Strict-Transport-Security",
            "Cross-Origin-Opener-Policy",
            "Cross-Origin-Embedder-Policy",
        ):
            self.assertNotIn("add_header " + name, self.nginx)
        self.assertEqual(self.headers[:2], self.headers[2:])
        self.assertEqual(len(probe.document_policy(Response(self.headers[:2]))), 64)

    def test_actual_header_guard_rejects_missing_weakened_duplicate_and_reporting_authority(
        self,
    ):
        original = self.headers[:2]
        changed = [original[:1], original + original[:1]]
        for before, after in (
            ("script-src 'self'", "script-src 'self' 'unsafe-eval'"),
            ("manifest-src 'self'", "manifest-src 'self'; report-uri /collect"),
            ("object-src 'none'", "object-src 'self'"),
        ):
            changed.append(
                [(key, value.replace(before, after)) for key, value in original]
            )
        for headers in changed:
            with self.assertRaises(AssertionError):
                probe.document_policy(Response(headers))

    def test_backend_redirect_retains_its_independent_nonce_policy(self):
        source = (ROOT / "backend/auth/google_redirect_bridge.py").read_text()
        self.assertIn("script-src 'nonce-{nonce}'", source)
        self.assertIn("connect-src 'self'", source)
        self.assertIn("frame-ancestors 'none'", source)


if __name__ == "__main__":
    unittest.main()
