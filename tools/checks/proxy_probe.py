"""Bounded nginx exercise; run only in the disposable network-none namespace.

At most 120 requests, 5/second, four callers and 55 seconds. An in-process fake
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

        do_PATCH = do_POST
        do_DELETE = do_POST

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
            if sent >= 120 or time.monotonic() - start >= 55:
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
                "cache_control": reply.getheader("Cache-Control"),
            }
            reply.read(65536)
            return result
        finally:
            conn.close()

    try:
        # Every request has a different claimed address and session. The actual
        # network peer is unchanged and must own one shared budget across workers.
        question_paths = (
            "/api/query",
            "/api/v1/chats",
            "/api/v1/chats/synthetic-chat/messages",
            "/api/v1/chats/synthetic-chat/messages/synthetic-input/retries",
        )
        for n in range(12):
            results.append(
                request(
                    path="/api/query" if baseline else question_paths[n % 4],
                    headers={
                        "CF-Connecting-IP": f"192.0.2.{n+1}",
                        "X-Forwarded-For": f"198.51.100.{n+1}",
                        "Forwarded": f"for=192.0.2.{n+1}",
                        "Cookie": f"synthetic-session={n}",
                    },
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
        # New first-question, append, and retry endpoints cannot create fresh
        # quotas; nginx normalizes escaped/repeated slashes before map matching.
        for path in question_paths[1:]:
            for alias in (
                path + "/",
                path.replace("chats", "%63hats"),
                path.replace("/api/", "/api//"),
            ):
                before = sum(calls.values())
                assert request(alias)["status"] == 429, alias
                assert sum(calls.values()) == before
        for method, path in (
            ("GET", "/api/v1/chats"),
            ("GET", "/api/v1/chats/synthetic-chat/messages"),
            ("POST", "/api/v1/chats/search"),
            ("PATCH", "/api/v1/chats/synthetic-chat"),
            ("DELETE", "/api/v1/chats/synthetic-chat?revision=1"),
            ("GET", "/api/v1/me/saved-prompts"),
        ):
            assert request(path, method=method)["status"] == 200
        # Auth has a separate budget. Logout and health remain usable during abuse.
        auth = [request("/api/auth/google") for _ in range(7)]
        assert any(r["status"] == 429 for r in auth)
        assert request("/api/auth/google/")["status"] == 429
        assert request("/api/auth/logout")["status"] == 200
        assert request("/api/health")["status"] == 200
        before = calls["/api/oversize"]
        oversize = request("/api/oversize", body=b"x" * 17000)
        assert oversize["status"] == 413 and oversize["cache_control"] == "no-store"
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
        # Password bootstrap shares the bounded challenge budget; the cost
        # routes have separate budgets so registration cannot spend recovery.
        for path in (
            "/api/v1/auth/bootstrap?action=login",
            "/api/v1/auth/bootstrap/",
            "/api/v1/auth/%62ootstrap",
            "/api//v1/auth/bootstrap",
        ):
            before = sum(calls.values())
            assert request(path, method="GET")["status"] == 429
            assert sum(calls.values()) == before
        password_paths = (
            "password-login",
            "registrations",
            "password-reset-requests",
            "email-verifications",
        )
        password_waves = {}
        for route in password_paths:
            before = sum(calls.values())
            wave = [
                request(
                    "/api/v1/auth/" + route,
                    headers={
                        "CF-Connecting-IP": f"192.0.2.{n+1}",
                        "Cookie": f"churn={n}",
                    },
                )
                for n in range(6)
            ]
            assert (
                wave[0]["status"] == 200
            )  # Previous route's flood cannot spend this route's quota.
            assert any(x["status"] == 429 for x in wave)
            assert all(x["status"] in {200, 429} for x in wave)
            assert sum(calls.values()) - before == sum(x["status"] == 200 for x in wave)
            password_waves[route] = wave
            for alias in (
                "/api/v1/auth/" + route + "/",
                "/api/v1/auth/%" + format(ord(route[0]), "02x") + route[1:],
                "/api//v1/auth/" + route,
            ):
                before = sum(calls.values())
                assert request(alias)["status"] == 429
                assert sum(calls.values()) == before
        for alias in (
            "/api/v1/auth/password-resets",
            "/api/v1/auth/password-resets/",
            "/api/v1/auth/%70assword-resets",
            "/api//v1/auth/password-resets",
        ):
            before = sum(calls.values())
            assert request(alias)["status"] == 429
            assert sum(calls.values()) == before
        assert request("/api/auth/logout")["status"] == 200
        assert request("/api/health")["status"] == 200
        time.sleep(12)
        for route in password_paths:
            assert request("/api/v1/auth/" + route)["status"] == 200
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
            "shared_workspace_question_budget": "passed",
            "personal_metadata_outside_question_budget": "passed",
            "challenge_bootstrap_budget": "passed",
            "password_route_budgets": "passed",
            "password_waves": password_waves,
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
