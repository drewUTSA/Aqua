"""Fake export upstream only; retain 120 requests/5s-1/4 callers/55s caps."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time

EXPORTS = "/api/v1/me/data-exports"
ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
DOWNLOAD = EXPORTS + "/" + ID + "/download"


def aliases(path):
    return (
        path,
        path + "/",
        path.replace("/api/", "/api//"),
        path.replace("/me/", "/%6de/"),
    )


def private_cache_headers(response):
    # nginx and the API may each add this same restrictive response header.
    # Inspect individual fields rather than http.client's comma-joined value.
    values = [
        value.strip().lower()
        for name, value in response.getheaders()
        if name.lower() == "cache-control"
    ]
    return bool(values) and all(value == "no-store" for value in values)


def probe():
    calls = Counter()
    release, complete = threading.Event(), threading.Event()
    body = b'{"synthetic":true,"padding":"' + b"x" * 4096 + b'"}'

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls[self.path] += 1
            self.send_response(200)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            if self.path == DOWNLOAD:
                self.send_header(
                    "Content-Disposition",
                    'attachment; filename="aqua-personal-data-v1.json"',
                )
            self.end_headers()
            if self.path == DOWNLOAD:
                self.wfile.write(body[:1])
                self.wfile.flush()
                release.wait(timeout=1.2)
                self.wfile.write(body[1:])
                self.wfile.flush()
                complete.set()
            else:
                self.wfile.write(body)

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.do_GET()

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    start, last, sent = time.monotonic(), 0.0, 0
    pacing = threading.Lock()

    def open_request(path, method):
        nonlocal last, sent
        with pacing:
            time.sleep(max(0, 0.21 - (time.monotonic() - last)))
            if sent >= 120 or time.monotonic() - start >= 55:
                raise RuntimeError("export_proxy_budget_exceeded")
            sent += 1
            number = sent
            last = time.monotonic()
        conn = HTTPConnection("127.0.0.1", 5173, timeout=2)
        try:
            conn.request(
                method,
                path,
                body=b"{}" if method == "POST" else None,
                headers={
                    "Cookie": "synthetic-session=" + str(number),
                    "X-Forwarded-For": "198.51.100." + str(number),
                    "CF-Connecting-IP": "192.0.2." + str(number),
                    "Accept-Encoding": "gzip",
                },
            )
            return conn, conn.getresponse()
        except Exception:
            conn.close()
            raise

    def request(path, method="GET"):
        conn, response = open_request(path, method)
        try:
            result = (
                response.status,
                response.getheader("Retry-After"),
                response.getheader("Cache-Control"),
            )
            assert len(response.read(65537)) <= 65536
            return result
        finally:
            conn.close()

    def denied(path):
        before = sum(calls.values())
        assert request(path, "POST") == (429, "12", "no-store")
        assert sum(calls.values()) == before

    try:
        metadata = (EXPORTS, EXPORTS + "/" + ID, EXPORTS + "/by-intent/" + ID)
        for path in metadata:
            assert request(path)[0] == 200
        assert request(EXPORTS, "POST")[0] == 200
        attempts = [request("/api/v1/me/reauth/password", "POST")[0] for _ in range(6)]
        assert attempts[0] == 200 and 429 in attempts and set(attempts) <= {200, 429}
        for path in aliases(EXPORTS):
            denied(path)
        before = sum(calls.values())
        with ThreadPoolExecutor(max_workers=4) as pool:
            statuses = list(pool.map(lambda _: request(EXPORTS, "POST")[0], range(4)))
        assert statuses == [429] * 4 and sum(calls.values()) == before
        exhausted = time.monotonic()
        for path in metadata:
            assert request(path)[0] == 200
        conn, response = open_request(DOWNLOAD, "GET")
        try:
            assert response.status == 200 and private_cache_headers(response)
            assert response.getheader("Content-Encoding") is None
            first = response.read(1)
            assert (
                first == body[:1] and not complete.is_set()
            ), "proxy_buffered_private_export"
            release.set()
            assert first + response.read(65536) == body
            assert (
                response.getheader("Content-Disposition")
                == 'attachment; filename="aqua-personal-data-v1.json"'
            )
        finally:
            conn.close()
        time.sleep(max(0, 12.2 - (time.monotonic() - exhausted)))
        assert request(EXPORTS, "POST")[0] == 200
        return {
            "mode": "blue_retest",
            "status": "passed",
            "requests": sent,
            "admitted_work": sum(calls.values()),
            "proof_zone_shared_with_creation": True,
            "metadata_outside_CPU_budget": True,
            "normalized_aliases": "passed",
            "forged_headers_and_cookies": "shared_peer_budget",
            "download_first_byte_before_upstream_complete": True,
            "private_attachment_uncompressed": True,
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
        release.set()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    print(json.dumps(probe()))
