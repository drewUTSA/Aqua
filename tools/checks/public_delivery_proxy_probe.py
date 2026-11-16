"""GET-only probe for an owned network-none nginx fixture with synthetic files."""

from http.client import HTTPConnection
import json
import sys
import time

MAX_REQUESTS = 48
MAX_SECONDS = 20
MAX_BODY = 65536


def probe(paths):
    started, last, count = time.monotonic(), 0.0, 0

    def get(path):
        nonlocal last, count
        time.sleep(max(0, 0.21 - (time.monotonic() - last)))
        if count >= MAX_REQUESTS or time.monotonic() - started >= MAX_SECONDS:
            raise RuntimeError("delivery_fixture_budget")
        count += 1
        last = time.monotonic()
        connection = HTTPConnection("127.0.0.1", 5173, timeout=2)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            body = response.read(MAX_BODY + 1)
            assert len(body) <= MAX_BODY, "delivery_body_budget"
            return response.status, response.getheader("Content-Type", ""), body
        finally:
            connection.close()

    assert len(paths) == 14 and len(set(paths)) == 14, "route_fixture_invalid"
    for path in paths:
        status, _, body = get(path)
        assert status == 200 and b'id="root"' in body, "legitimate_route_missing"
        assert b'name="robots" content="noindex, nofollow"' in body, "noindex_missing"
    for path in (
        "/settings?tab=appearance",
        "/verify-email?ignored=synthetic",
        "/account-action/email_change_old?ignored=synthetic",
    ):
        status, _, body = get(path)
        assert status == 200 and b'id="root"' in body, "query_route_changed"
    for path in (
        "/missing",
        "/settings/",
        "/settings/missing",
        "/signin/extra",
        "/account-action/missing",
        "/assets/missing.js",
        "/missing.js",
    ):
        status, _, body = get(path)
        assert status == 404 and b'id="root"' not in body, "missing_route_shell"
    status, kind, body = get("/robots.txt")
    assert status == 200 and kind.startswith("text/plain"), "robots_type"
    assert body == b"User-agent: *\nDisallow: /\n", "robots_policy"
    status, kind, body = get("/sitemap.xml")
    assert status == 404 and kind.startswith("text/plain"), "sitemap_policy"
    assert b"<html" not in body.lower(), "sitemap_html"
    status, _, body = get("/assets/synthetic.js")
    assert status == 200 and body == b"/* synthetic asset */", "asset_delivery"
    status, _, body = get("/fixture-icon.svg")
    assert status == 200 and body == b"<svg/>", "public_file_delivery"
    status, kind, body = get("/api/ready")
    assert status == 404 and kind.startswith("application/json"), "readiness_exposed"
    assert body == b'{"detail":"Not found"}', "readiness_body_changed"
    return {
        "status": "passed",
        "requests": count,
        "routes": len(paths),
        "network": "none",
        "max_requests": MAX_REQUESTS,
        "max_seconds": MAX_SECONDS,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


if __name__ == "__main__":
    print(json.dumps(probe(json.loads(sys.argv[1]))))
