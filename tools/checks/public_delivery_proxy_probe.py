"""GET-only probe for an owned network-none nginx fixture with synthetic files."""

from http.client import HTTPConnection
import hashlib
import json
import re
import sys
import time

MAX_REQUESTS = 48
MAX_SECONDS = 20
MAX_BODY = 65536


def document_policy(response):
    """Compare public policy categories, never collect request URLs or samples."""
    headers = response.getheaders()
    names = [name.lower() for name, _ in headers]
    assert names.count("content-security-policy") == 1, "document_csp_missing"
    assert (
        names.count("content-security-policy-report-only") == 0
    ), "unexpected_report_only_policy"

    def directives(name):
        parts = [part.strip().split() for part in response.getheader(name).split(";")]
        assert all(parts) and len({part[0] for part in parts}) == len(
            parts
        ), "document_csp_duplicate"
        return {part[0]: " ".join(part[1:]) for part in parts}

    baseline = {
        "object-src": "'none'",
        "base-uri": "'none'",
        "frame-ancestors": "'none'",
    }
    candidate = {
        **baseline,
        "default-src": "'none'",
        "script-src": "'self' https://accounts.google.com/gsi/client",
        "script-src-attr": "'none'",
        "style-src": "'self' 'unsafe-inline' https://accounts.google.com/gsi/style",
        "img-src": "'self' data:",
        "font-src": "'self'",
        "connect-src": "'self' https://accounts.google.com/gsi/",
        "frame-src": "https://accounts.google.com/gsi/",
        "form-action": "'self'",
        "worker-src": "'none'",
        "media-src": "'none'",
        "manifest-src": "'self'",
    }
    assert (
        directives("Content-Security-Policy") == candidate
    ), "document_csp_candidate_changed"
    encoded = json.dumps(
        [response.getheader("Content-Security-Policy")],
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def probe(paths, recovery_sha256):
    started, last, count = time.monotonic(), 0.0, 0
    policy_hashes = set()
    policy_responses = 0

    def get(path, *, document=False, isolated=False, hostname=None):
        nonlocal last, count, policy_responses
        time.sleep(max(0, 0.21 - (time.monotonic() - last)))
        if count >= MAX_REQUESTS or time.monotonic() - started >= MAX_SECONDS:
            raise RuntimeError("delivery_fixture_budget")
        count += 1
        last = time.monotonic()
        connection = HTTPConnection("127.0.0.1", 5173, timeout=2)
        try:
            connection.request(
                "GET", path, headers={"Host": hostname} if hostname else {}
            )
            response = connection.getresponse()
            if path == "/api":
                assert response.getheader("Location") is None, "bare_api_redirect"
            body = response.read(MAX_BODY + 1)
            assert len(body) <= MAX_BODY, "delivery_body_budget"
            headers = {name.lower(): value for name, value in response.getheaders()}
            for name, expected in (
                ("strict-transport-security", "max-age=31536000; includeSubDomains"),
                ("cross-origin-opener-policy", "same-origin-allow-popups"),
                ("cross-origin-resource-policy", "same-origin"),
            ):
                assert headers.get(name) == expected, "response_security_header_changed"
            permissions = headers.get("permissions-policy", "").split(", ")
            assert all(
                item.endswith("=()") for item in permissions
            ), "permissions_policy_open"
            disabled = {
                "accelerometer",
                "autoplay",
                "bluetooth",
                "browsing-topics",
                "camera",
                "captured-surface-control",
                "clipboard-read",
                "compute-pressure",
                "deferred-fetch",
                "deferred-fetch-minimal",
                "digital-credentials-create",
                "digital-credentials-get",
                "display-capture",
                "encrypted-media",
                "fullscreen",
                "gamepad",
                "geolocation",
                "gyroscope",
                "hid",
                "idle-detection",
                "interest-cohort",
                "keyboard-map",
                "language-detector",
                "language-model",
                "local-fonts",
                "local-network",
                "local-network-access",
                "loopback-network",
                "magnetometer",
                "media-playback-while-not-visible",
                "microphone",
                "midi",
                "on-device-speech-recognition",
                "otp-credentials",
                "payment",
                "picture-in-picture",
                "private-state-token-issuance",
                "private-state-token-redemption",
                "publickey-credentials-create",
                "publickey-credentials-get",
                "screen-wake-lock",
                "serial",
                "speaker-selection",
                "summarizer",
                "sync-xhr",
                "translator",
                "usb",
                "web-app-installation",
                "window-management",
                "xr-spatial-tracking",
            }
            assert {f"{feature}=()" for feature in disabled} <= set(permissions)
            assert (
                "clipboard-write=()" not in permissions
                and "identity-credentials-get=()" not in permissions
            )
            assert (
                "cross-origin-embedder-policy" not in headers
            ), "unexpected_embedder_policy"
            if document:
                policy_hashes.add(document_policy(response))
                policy_responses += 1
            if isolated:
                assert (
                    response.getheader("Content-Security-Policy") is None
                    and response.getheader("Content-Security-Policy-Report-Only")
                    is None
                ), "competing_document_csp"
            return response.status, response.getheader("Content-Type", ""), body
        finally:
            connection.close()

    assert len(paths) == 14 and len(set(paths)) == 14, "route_fixture_invalid"
    for path in paths:
        status, _, body = get(path, document=True)
        assert status == 200 and b'id="root"' in body, "legitimate_route_missing"
        assert b'name="robots" content="noindex, nofollow"' in body, "noindex_missing"
    for path in (
        "/settings?tab=appearance",
        "/verify-email?ignored=synthetic",
        "/account-action/email_change_old?ignored=synthetic",
    ):
        status, _, body = get(path, document=True)
        assert status == 200 and b'id="root"' in body, "query_route_changed"
    for path in (
        "/missing",
        "/settings/",
        "/settings/missing",
        "/signin/extra",
        "/account-action/missing",
        "/assets/missing.js",
        "/missing.js",
        "/unknown-resource?source=synthetic",
        "/404.html",
        "/50x.html",
    ):
        status, kind, body = get(
            path,
            document=not path.startswith("/assets/"),
            isolated=path.startswith("/assets/"),
        )
        assert status == 404 and b'id="root"' not in body, "missing_route_shell"
        if path.startswith("/assets/"):
            assert hashlib.sha256(body).hexdigest() != recovery_sha256
        else:
            assert kind.startswith("text/html"), "missing_document_type"
            assert (
                hashlib.sha256(body).hexdigest() == recovery_sha256
            ), "missing_document_recovery"
    for hostname in ("aqua-ai.us", "api.aqua-ai.us"):
        status, kind, body = get("/.well-known/security.txt", hostname=hostname)
        assert status == 200 and kind.startswith("text/plain"), "security_contact_type"
        lines = body.decode("utf-8").splitlines()
        assert any(
            re.fullmatch(r"Contact: (?:mailto:|https://)\S+", line) for line in lines
        )
        assert any(
            re.fullmatch(r"Expires: \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", line)
            for line in lines
        )
    status, kind, body = get("/robots.txt")
    assert status == 200 and kind.startswith("text/plain"), "robots_type"
    assert body == b"User-agent: *\nDisallow: /\n", "robots_policy"
    status, kind, body = get("/sitemap.xml")
    assert status == 404 and kind.startswith("text/plain"), "sitemap_policy"
    assert b"<html" not in body.lower(), "sitemap_html"
    status, _, body = get("/assets/synthetic.js", isolated=True)
    assert status == 200 and body == b"/* synthetic asset */", "asset_delivery"
    status, _, body = get("/fixture-icon.svg", document=True)
    assert status == 200 and body == b"<svg/>", "public_file_delivery"
    for hostname in ("aqua-ai.us", "api.aqua-ai.us"):
        status, kind, body = get("/api", isolated=True, hostname=hostname)
        assert status == 404 and kind.startswith("application/json"), "bare_api_exposed"
        assert body == b'{"detail":"Not found"}', "bare_api_body_changed"
    status, kind, body = get("/api/ready", isolated=True)
    assert status == 404 and kind.startswith("application/json"), "readiness_exposed"
    assert body == b'{"detail":"Not found"}', "readiness_body_changed"
    # No upstream runs in this isolated fixture. Preserve a real gateway failure.
    status, _, body = get("/api/health", isolated=True)
    assert (
        status == 502 and hashlib.sha256(body).hexdigest() != recovery_sha256
    ), "upstream_failure_rewritten"
    assert len(policy_hashes) == 1 and policy_responses > 0, "document_csp_inconsistent"
    return {
        "status": "passed",
        "requests": count,
        "routes": len(paths),
        "network": "none",
        "max_requests": MAX_REQUESTS,
        "max_seconds": MAX_SECONDS,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "document_policy_responses": policy_responses,
        "document_policy_sha256": next(iter(policy_hashes)),
    }


if __name__ == "__main__":
    print(json.dumps(probe(json.loads(sys.argv[1]), sys.argv[2])))
