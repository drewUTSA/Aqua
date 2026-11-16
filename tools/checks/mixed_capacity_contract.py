"""Closed P12 synthetic HTTP work and metadata-only measurement contracts."""

import math
import re
import threading
import time

LIMITS = {
    "work_seconds": 150,
    "whole_fixture_seconds": 180,
    "resource_cleanup_seconds": 60,
    "app_shutdown_seconds": 15,
    "http_requests": 200,
    "concurrent_reads": 4,
    "concurrent_http": 6,
    "mixed_reads": 96,
    "fake_jobs": 6,
    "stream_connections": 2,
    "stream_events": 24,
    "stream_bytes": 8192,
    "request_bytes": 4096,
    "response_bytes": 65536,
    "http_timeout_seconds": 3,
}
READ_PATHS = ("/api/auth/me", "/api/v1/me", "/api/v1/chats?limit=20")
LABELS = ("session", "profile", "history")
JOB_QUESTIONS = (
    "P12 held generation",
    "P12 held execution",
    "P12 queued recovery A",
    "P12 queued recovery B",
    "P12 completed recovery A",
    "P12 completed recovery B",
)
REQUEST = re.compile(
    r"/api/v1/analysis-requests/[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}(?:/(?:cancel|events))?\Z"
)


def route_label(method, path):
    if method == "GET" and path in READ_PATHS:
        return LABELS[READ_PATHS.index(path)]
    if (method, path) == ("GET", "/api/health"):
        return "health"
    if (method, path) == ("POST", "/api/v1/chats"):
        return "submit"
    if REQUEST.fullmatch(path):
        if method == "GET" and path.endswith("/events"):
            return "stream"
        if method == "POST" and path.endswith("/cancel"):
            return "cancel"
        if method == "GET" and not path.endswith(("/events", "/cancel")):
            return "snapshot"
    raise ValueError("mixed_http_route_denied")


def distribution(values):
    if not values or any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("mixed_measurements_invalid")
    ordered = sorted(values)
    result = {
        "samples": len(values),
        "p50_ms": round(ordered[math.ceil(len(values) * 0.5) - 1], 4),
        "max_ms": round(ordered[-1], 4),
    }
    # At least twenty observations are needed for this tail description. No p99.
    if len(values) >= 20:
        result["p95_ms"] = round(ordered[math.ceil(len(values) * 0.95) - 1], 4)
    return result


class Meter:
    def __init__(self):
        self.lock = threading.Lock()
        self.started = time.perf_counter()
        self.requests = self.active = self.maximum_active = 0
        self.samples, self.statuses, self.bytes = {}, {}, 0

    def reserve(self):
        with self.lock:
            if (
                self.requests >= LIMITS["http_requests"]
                or self.active >= LIMITS["concurrent_http"]
            ):
                raise ValueError("mixed_http_admission_bound")
            self.requests += 1
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)

    def finish(self, label, status, milliseconds, size):
        with self.lock:
            self.active -= 1
            if self.active < 0 or label not in {
                *LABELS,
                "health",
                "submit",
                "snapshot",
                "cancel",
                "stream",
            }:
                raise ValueError("mixed_http_measurement_shape")
            self.samples.setdefault(label, []).append(milliseconds)
            key = f"{label}:{status}"
            self.statuses[key] = self.statuses.get(key, 0) + 1
            self.bytes += size

    def report(self):
        with self.lock:
            if self.active or self.requests != sum(map(len, self.samples.values())):
                raise ValueError("mixed_http_completion_unconfirmed")
            elapsed = time.perf_counter() - self.started
            return {
                "requests": self.requests,
                "maximum_inflight_http": self.maximum_active,
                "response_bytes": self.bytes,
                "elapsed_seconds": round(elapsed, 4),
                "completed_requests_per_second": round(self.requests / elapsed, 4),
                "status_counts": dict(self.statuses),
                "latency": {
                    key: distribution(values) for key, values in self.samples.items()
                },
            }
