"""Additional identity-route exercise in a fresh network-none fake namespace.

The original proxy exercise remains required. This separate run retains the
same 120-request, 5/second, four-caller and 55-second ceilings.
"""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time

BOOTSTRAP = (
    "/api/v1/me/reauth/google-challenges",
    "/api/v1/me/google-link-challenges",
    "/api/v1/me/password-enrollments",
    "/api/v1/me/email-change-requests",
)
PROOFS = (
    ("POST", "/api/v1/me/reauth/google"),
    ("POST", "/api/v1/me/google-link-candidates"),
    ("POST", "/api/v1/me/google-links"),
    ("POST", "/api/v1/me/methods/google/synthetic-identity/revocations"),
    ("POST", "/api/v1/me/password"),
    ("PUT", "/api/v1/me/email"),
)


def aliases(path):
    """Canonical and three normalized aliases, without caller-chosen URLs."""
    return (
        path,
        path + "/",
        path.replace("/api/", "/api//"),
        path.replace("/me/", "/%6de/"),
    )


def probe():
    calls = Counter()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls[self.path] += 1
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"synthetic":true}')

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.do_GET()

        do_PUT = do_POST

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    start, last, sent = time.monotonic(), 0.0, 0
    pacing = threading.Lock()

    def request(path, method="POST"):
        nonlocal last, sent
        with pacing:
            time.sleep(max(0, 0.21 - (time.monotonic() - last)))
            if sent >= 120 or time.monotonic() - start >= 55:
                raise RuntimeError("identity_proxy_budget_exceeded")
            sent += 1
            current = sent
            last = time.monotonic()
        conn = HTTPConnection("127.0.0.1", 5173, timeout=2)
        try:
            conn.request(
                method,
                path,
                body=b"{}",
                headers={
                    "Cookie": f"synthetic-session={current}",
                    "X-Forwarded-For": f"198.51.100.{current}",
                    "CF-Connecting-IP": f"192.0.2.{current}",
                },
            )
            response = conn.getresponse()
            value = (
                response.status,
                response.getheader("Retry-After"),
                response.getheader("Cache-Control"),
            )
            response.read(65536)
            return value
        finally:
            conn.close()

    def denied(path, method="POST"):
        before = sum(calls.values())
        status, retry, cache = request(path, method)
        assert (status, retry, cache) == (429, "12", "no-store")
        assert sum(calls.values()) == before

    try:
        # Exhaust the existing bootstrap zone before attempting every new
        # bootstrap route. Forged peer headers/cookies cannot create a quota.
        bootstrap = [request("/api/v1/me/reauth-challenges") for _ in range(8)]
        assert bootstrap[0][0] == 200 and any(r[0] == 429 for r in bootstrap)
        assert all(r[0] in {200, 429} for r in bootstrap)
        for path in BOOTSTRAP:
            for alias in aliases(path):
                denied(alias)

        # A fresh proof zone is separate from bootstrap, and every new Google,
        # email and first-password operation spends that same proof budget.
        proof = [request("/api/v1/me/reauth/password") for _ in range(6)]
        assert proof[0][0] == 200 and any(r[0] == 429 for r in proof)
        assert all(r[0] in {200, 429} for r in proof)
        for method, path in PROOFS:
            for alias in aliases(path):
                denied(alias, method)
        before = sum(calls.values())
        with ThreadPoolExecutor(max_workers=4) as pool:
            concurrent = list(
                pool.map(lambda _: request("/api/v1/me/google-links"), range(4))
            )
        assert all(r[0] == 429 for r in concurrent)
        assert sum(calls.values()) == before
        # Recovery starts after the flood, including request pacing. Starting
        # the clock before the first request can test before one token drains.
        proof_start = time.monotonic()
        for method, path in (
            ("GET", "/api/v1/me/notification-settings"),
            ("PUT", "/api/v1/me/notification-settings"),
            ("GET", "/api/v1/me/methods"),
            ("GET", "/api/v1/me/sessions"),
        ):
            assert request(path, method)[0] == 200

        time.sleep(max(0, 12.2 - (time.monotonic() - proof_start)))
        assert request("/api/v1/me/reauth/google")[0] == 200
        assert request(BOOTSTRAP[0])[0] == 200
        return {
            "mode": "blue_retest",
            "status": "passed",
            "requests": sent,
            "admitted_work": sum(calls.values()),
            "identity_bootstrap_paths": len(BOOTSTRAP),
            "identity_proof_paths": len(PROOFS),
            "normalized_aliases": "passed",
            "forged_headers_and_cookies": "shared_peer_budget",
            "metadata_outside_cpu_budget": "passed",
            "concurrent_callers": 4,
            "recovery": "passed",
            "duration_seconds": round(time.monotonic() - start, 2),
            "limits": {
                "requests": 120,
                "requests_per_second": 5,
                "callers": 4,
                "seconds": 55,
            },
        }
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    print(json.dumps(probe()))
