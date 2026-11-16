"""Closed SPA/discovery contract, with all existing proxy boundaries retained."""

import hashlib
from html.parser import HTMLParser
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

import run_public_delivery_proxy as fixture

ROOT = Path(__file__).resolve().parents[2]
PROTECTED_PREFIX_SHA256 = (
    "f0362eb481bbc6e08a83e119286cba168bfa9165c240729f2c85466a0d5637ac"
)


class Metadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.robots = []

    def handle_starttag(self, tag, attributes):
        values = dict(attributes)
        if tag == "meta" and values.get("name") == "robots":
            self.robots.append(values.get("content", ""))


class PublicDeliveryRoutes(unittest.TestCase):
    def test_every_frontend_local_route_and_only_those_routes_get_the_shell(self):
        nginx = (ROOT / "frontend/nginx.conf").read_text()
        routes = fixture.local_paths(
            (ROOT / "frontend/src/services/routes.js").read_text()
        )
        line = next(
            line.strip()
            for line in nginx.splitlines()
            if line.strip().startswith("location ~ ^/(?:settings|")
        )
        pattern = re.compile(line.removeprefix("location ~ ").removesuffix(" {"))
        self.assertEqual(len(routes), 14)
        for path in routes:
            self.assertIsNotNone(pattern.fullmatch(path), path)
        for path in (
            "/missing",
            "/settings/",
            "/settings/missing",
            "/signin/",
            "/signin/missing",
            "/account-action",
            "/account-action/password_add/",
            "/account-action/password_additional",
            "/privacy/missing",
            "/api/v1/me",
            "/assets/missing.js",
            "/robots.txt",
            "/sitemap.xml",
        ):
            self.assertIsNone(pattern.fullmatch(path), path)
        self.assertNotIn("try_files $uri $uri/ /index.html", nginx)
        self.assertIn("try_files /index.html =404;", nginx)

    def test_all_previous_api_rate_export_security_and_asset_bytes_are_unchanged(self):
        source = (ROOT / "frontend/nginx.conf").read_bytes()
        prefix = source.split(b"    # Restricted launch:")[0]
        # Computed independently from c62baaa before editing; includes all maps,
        # auth/API/export/rate/stream locations and the immutable-assets location.
        self.assertEqual(hashlib.sha256(prefix).hexdigest(), PROTECTED_PREFIX_SHA256)

    def test_restricted_html_metadata_is_explicit_and_unambiguous(self):
        parser = Metadata()
        parser.feed((ROOT / "frontend/index.html").read_text())
        self.assertEqual(len(parser.robots), 1)
        self.assertEqual(
            {part.strip() for part in parser.robots[0].split(",")},
            {"noindex", "nofollow"},
        )

    def test_existing_receipt_is_refused_before_any_fixture_action(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing.json"
            output.write_text("preserve")
            with (
                mock.patch.object(fixture, "docker") as docker,
                mock.patch.object(fixture, "create") as create,
            ):
                with self.assertRaisesRegex(ValueError, "output_already_exists"):
                    fixture.run(output)
                docker.assert_not_called()
                create.assert_not_called()
            self.assertEqual(output.read_text(), "preserve")


if __name__ == "__main__":
    unittest.main()
