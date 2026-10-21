"""Bounded nginx exercise; run only in the disposable network-none namespace.

At most 100 requests, 5/second, four callers and 55 seconds. An in-process fake
upstream counts admitted work; no authentication provider or application runs.
"""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time


def probe(baseline: bool = False) -> dict:
    calls: Counter = Counter()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.answer()

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.answer()

        def answer(self):
            calls[self.path] += 1
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"synthetic":true}')

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    start, last, sent = time.monotonic(), 0.0, 0
    pace = threading.Lock()
    results = []

    def request(path="/api/query", headers=None, body=b"{}", method="POST"):
        nonlocal last, sent
        with pace:
            time.sleep(max(0, 0.21 - (time.monotonic() - last)))
            if sent >= 100 or time.monotonic() - start >= 55:
                raise RuntimeError("exercise budget exceeded")
            sent += 1
            last = time.monotonic()
        conn = HTTPConnection("127.0.0.1", 5173, timeout=2)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            reply = conn.getresponse()
            result = {
                "status": reply.status,
                "retry_after": reply.getheader("Retry-After"),
            }
            reply.read(65536)
            return result
        finally:
            conn.close()

    try:
        # Every request has a different claimed address and session. The actual
        # network peer is unchanged and must own one shared budget across workers.
        for n in range(12):
            results.append(
                request(
                    headers={
                        "CF-Connecting-IP": f"192.0.2.{n+1}",
                        "X-Forwarded-For": f"198.51.100.{n+1}",
                        "Forwarded": f"for=192.0.2.{n+1}",
                        "Cookie": f"synthetic-session={n}",
                    }
                )
            )
        if baseline:
            assert all(r["status"] == 200 for r in results), results
            return {
                "mode": "red_baseline",
                "finding": "forged_header_creates_fresh_query_budget",
                "requests": sent,
                "admitted_work": sum(calls.values()),
                "statuses": results,
            }
        assert any(r["status"] == 429 for r in results), results
        assert all(r["status"] in {200, 429} for r in results), results
        assert sum(calls.values()) == sum(r["status"] == 200 for r in results)
        assert sum(r["status"] == 200 for r in results) <= 6
        for path in ("/api/query/", "/api/%71uery", "/api//query"):
            before = sum(calls.values())
            reply = request(path)
            assert reply["status"] == 429, (path, reply)
            assert sum(calls.values()) == before
            assert reply["retry_after"] == "12"
        # Auth has a separate budget. Logout and health remain usable during abuse.
        auth = [request("/api/auth/google") for _ in range(7)]
        assert any(r["status"] == 429 for r in auth)
        assert request("/api/auth/google/")["status"] == 429
        assert request("/api/auth/logout")["status"] == 200
        assert request("/api/health")["status"] == 200
        before = calls["/api/oversize"]
        assert request("/api/oversize", body=b"x" * 17000)["status"] == 413
        assert calls["/api/oversize"] == before
        for path in ("/api/ready", "/api/ready/", "/api/%72eady", "/api//ready"):
            before = sum(calls.values())
            assert request(path)["status"] == 404
            assert sum(calls.values()) == before
        before = sum(calls.values())
        bootstrap = [
            request(
                "/api/auth/config",
                method="GET",
                headers={
                    "X-Forwarded-For": f"198.51.100.{n+1}",
                    "CF-Connecting-IP": f"192.0.2.{n+1}",
                    "Cookie": f"churn={n}",
                },
            )
            for n in range(9)
        ]
        assert any(r["status"] == 429 for r in bootstrap)
        assert sum(calls.values()) - before == sum(
            r["status"] == 200 for r in bootstrap
        )
        for path in ("/api/auth/config/", "/api/auth/%63onfig", "/api//auth/config"):
            before = sum(calls.values())
            assert request(path, method="GET")["status"] == 429
            assert sum(calls.values()) == before
        time.sleep(12)
        assert request()["status"] == 200
        assert request("/api/auth/config", method="GET")["status"] == 200
        before = sum(calls.values())
        with ThreadPoolExecutor(max_workers=4) as pool:
            wave = list(pool.map(lambda _: request("/api/auth/google"), range(4)))
        assert any(r["status"] == 429 for r in wave)
        assert sum(calls.values()) - before == sum(r["status"] == 200 for r in wave)
        return {
            "mode": "blue_retest",
            "status": "passed",
            "requests": sent,
            "admitted_work": sum(calls.values()),
            "query_statuses": results,
            "auth_statuses": auth,
            "concurrent_wave": wave,
            "recovery": "passed",
            "private_readiness_boundary": "passed",
            "challenge_bootstrap_budget": "passed",
            "duration_seconds": round(time.monotonic() - start, 2),
        }
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", action="store_true")
    args = parser.parse_args()
    print(json.dumps(probe(args.baseline)))
