"""Fixed loopback HTTP mix, held SSE consumers and recovery observations."""

from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import threading
import time
from uuid import uuid4

from mixed_capacity_contract import (
    JOB_QUESTIONS,
    LABELS,
    LIMITS,
    READ_PATHS,
    distribution,
    route_label,
)


class Client:
    def __init__(self, runtime, meter):
        self.runtime, self.meter = runtime, meter
        self.streams = self.stream_events = self.stream_bytes = 0
        self.lock = threading.Lock()

    def headers(self, actor):
        return {
            "Cookie": actor.cookie,
            "Origin": self.runtime.settings.app_origin,
            "X-CSRF-Token": actor.csrf,
            "Accept": "application/json",
            "Connection": "close",
        }

    def request(self, actor, method, path, body=None, expected=(200,)):
        label = route_label(method, path)
        raw = json.dumps(body).encode() if body is not None else None
        if raw is not None and len(raw) > LIMITS["request_bytes"]:
            raise ValueError("mixed_request_byte_bound")
        self.meter.reserve()
        started, status, size = time.perf_counter(), 0, 0
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.runtime.port, timeout=LIMITS["http_timeout_seconds"]
        )
        try:
            headers = self.headers(actor)
            if raw is not None:
                headers["Content-Type"] = "application/json"
            connection.request(method, path, body=raw, headers=headers)
            response = connection.getresponse()
            status = response.status
            if (
                response.getheader("Content-Type", "").split(";", 1)[0]
                != "application/json"
                or response.getheader("Cache-Control") != "no-store"
            ):
                raise ValueError("mixed_private_delivery_invalid")
            length = response.getheader("Content-Length")
            if length is not None and (
                not length.isascii()
                or not length.isdigit()
                or len(length) > 10
                or int(length) > LIMITS["response_bytes"]
            ):
                raise ValueError("mixed_response_byte_bound")
            data = response.read(LIMITS["response_bytes"] + 1)
            size = len(data)
            if size > LIMITS["response_bytes"] or status not in expected:
                raise ValueError("mixed_http_outcome_invalid")
            value = json.loads(data)
            if type(value) is not dict:
                raise ValueError("mixed_json_response_invalid")
            return value
        finally:
            connection.close()
            self.meter.finish(
                label, status, (time.perf_counter() - started) * 1000, size
            )

    def stream(self, actor, request_id, ready, release, *, slow=False):
        path = f"/api/v1/analysis-requests/{request_id}/events"
        assert route_label("GET", path) == "stream"
        with self.lock:
            if self.streams >= LIMITS["stream_connections"]:
                raise ValueError("mixed_stream_connection_bound")
            self.streams += 1
        self.meter.reserve()
        started, status, size = time.perf_counter(), 0, 0
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.runtime.port, timeout=LIMITS["http_timeout_seconds"]
        )
        response = None
        try:
            connection.request("GET", path, headers=self.headers(actor))
            response = connection.getresponse()
            status = response.status
            if (
                status != 200
                or response.getheader("Content-Type", "").split(";", 1)[0]
                != "text/event-stream"
                or response.getheader("Cache-Control") != "no-store"
            ):
                raise ValueError("mixed_stream_delivery_invalid")
            prefix = b""
            if slow:
                for _ in range(16):
                    prefix += response.read(1)
                    time.sleep(0.04)
            lines = []
            for _ in range(8):
                line = prefix + response.readline(513)
                prefix = b""
                size += len(line)
                if len(line) > 512 or size > LIMITS["stream_bytes"]:
                    raise ValueError("mixed_stream_byte_bound")
                lines.append(line)
                if line == b"\n":
                    break
            values = [line[6:] for line in lines if line.startswith(b"data: ")]
            if len(values) != 1:
                raise ValueError("mixed_stream_event_missing")
            value = json.loads(values[0])
            if (
                set(value) != {"request_id", "sequence", "version", "state", "stage"}
                or value["request_id"] != request_id
                or type(value["sequence"]) is not int
                or not 0 <= value["sequence"] <= 32
            ):
                raise ValueError("mixed_stream_metadata_invalid")
            with self.lock:
                self.stream_events += 1
                self.stream_bytes += size
                if (
                    self.stream_events > LIMITS["stream_events"]
                    or self.stream_bytes > LIMITS["stream_bytes"]
                ):
                    raise ValueError("mixed_stream_total_bound")
            ready.set()
            if not release.wait(20):
                raise ValueError("mixed_stream_hold_deadline")
        finally:
            if response is not None:
                response.close()
            connection.close()
            self.meter.finish(
                "stream", status, (time.perf_counter() - started) * 1000, size
            )


def submit(client, actor, question):
    value = client.request(
        actor,
        "POST",
        "/api/v1/chats",
        {"client_request_id": str(uuid4()), "question": question, "model": "ollama"},
        expected=(202,),
    )
    request_id = value["request"]["id"]
    route_label("GET", "/api/v1/analysis-requests/" + request_id)
    client.runtime.history[actor.owner].add(value["chat"]["id"])
    return request_id


def wait_jobs(client, jobs):
    remaining, values = dict(jobs), {}
    for _ in range(12):
        for request_id, (actor, expected) in tuple(remaining.items()):
            value = client.request(
                actor, "GET", "/api/v1/analysis-requests/" + request_id
            )
            if value["chat"]["id"] not in client.runtime.history[actor.owner]:
                raise ValueError("mixed_snapshot_owner_mismatch")
            if value["request"]["state"] == expected:
                values[request_id] = value
                del remaining[request_id]
        if not remaining:
            return values
        time.sleep(0.1)
    raise ValueError("mixed_job_terminal_deadline")


def idle_state(runtime):
    with runtime.storage.transaction() as conn:
        return conn.execute(
            "SELECT user_id,last_activity_at,idle_expires_at FROM app.sessions ORDER BY user_id"
        ).fetchall()


def mixed_reads(client):
    def owner_reads(index, actor):
        for round_number in range(24):
            route_index = (round_number + index) % len(READ_PATHS)
            value = client.request(actor, "GET", READ_PATHS[route_index])
            if route_index < 2:
                if (
                    value["user"]["id"] != actor.owner
                    or route_index == 0
                    and value["can_query"] is not actor.granted
                ):
                    raise ValueError("mixed_account_isolation_failed")
            else:
                ids = [item["id"] for item in value["items"]]
                if (
                    len(ids) != 20
                    or len(set(ids)) != 20
                    or not set(ids) <= client.runtime.history[actor.owner]
                ):
                    raise ValueError("mixed_history_isolation_failed")

    before = idle_state(client.runtime)
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=LIMITS["concurrent_reads"]) as workers:
        work = [
            workers.submit(owner_reads, index, actor)
            for index, actor in enumerate(client.runtime.actors)
        ]
        for future in work:
            future.result(timeout=30)
    elapsed = time.perf_counter() - started
    if idle_state(client.runtime) != before:
        raise ValueError("mixed_read_idle_extension")
    counts = {label: len(client.meter.samples.get(label, [])) for label in LABELS}
    if counts != {label: 32 for label in LABELS}:
        raise ValueError("mixed_read_distribution_changed")
    return {
        "samples": 96,
        "per_route": counts,
        "elapsed_seconds": round(elapsed, 4),
        "completed_reads_per_second": round(96 / elapsed, 4),
        "session_idle_unchanged": True,
        "owner_isolation": True,
        "granted_owners": 2,
        "account_only_owners": 2,
        "latency": {
            label: distribution(client.meter.samples[label][:]) for label in LABELS
        },
    }


def exercise(runtime, meter):
    client = Client(runtime, meter)
    first, second = runtime.actors[:2]
    until = time.monotonic() + 8
    while not runtime.server.started:
        if not runtime.thread.is_alive() or time.monotonic() >= until:
            raise ValueError("mixed_server_start_failed")
        time.sleep(0.05)
    runtime.phase = "readiness"
    client.request(first, "GET", "/api/health")
    runtime.phase = "grant_denials"
    for actor in runtime.actors[2:]:
        client.request(
            actor,
            "POST",
            "/api/v1/chats",
            {"client_request_id": str(uuid4()), "question": JOB_QUESTIONS[0]},
            expected=(403,),
        )
    runtime.phase = "admitted_fake_jobs"
    held = [
        submit(client, actor, question)
        for actor, question in zip((first, second), JOB_QUESTIONS[:2])
    ]
    for question in JOB_QUESTIONS[:2]:
        if not runtime.engine.entered[question].wait(5):
            raise ValueError("mixed_held_job_not_running")
    queued = [
        submit(client, actor, question)
        for actor, question in zip((first, second), JOB_QUESTIONS[2:4])
    ]
    runtime.phase = "http_streams"
    release = threading.Event()
    ready = [threading.Event(), threading.Event()]
    try:
        with ThreadPoolExecutor(max_workers=2) as streams:
            consumers = [
                streams.submit(
                    client.stream, actor, request_id, event, release, slow=index == 1
                )
                for index, (actor, request_id, event) in enumerate(
                    zip((first, second), held, ready)
                )
            ]
            try:
                if not all(event.wait(4) for event in ready):
                    raise ValueError("mixed_stream_start_failed")
                runtime.phase = "mixed_reads"
                reads = mixed_reads(client)
            finally:
                release.set()
            for consumer in consumers:
                consumer.result(timeout=4)
    finally:
        release.set()
    runtime.phase = "stream_disconnect_cleanup"
    until = time.monotonic() + 3
    while True:
        with runtime.storage.transaction() as conn:
            count = conn.execute(
                "SELECT count(*) FROM app.analysis_streams"
            ).fetchone()[0]
        if count == 0:
            break
        if time.monotonic() >= until:
            raise ValueError("mixed_stream_lease_not_released")
        time.sleep(0.05)
    runtime.phase = "cancel_and_queue_recovery"
    for actor, request_id in zip((first, second), held):
        client.request(
            actor,
            "POST",
            f"/api/v1/analysis-requests/{request_id}/cancel",
            {},
            expected=(200, 202),
        )
    wait_jobs(
        client,
        {
            **{
                ident: (actor, "cancelled")
                for ident, actor in zip(held, (first, second))
            },
            **{
                ident: (actor, "complete")
                for ident, actor in zip(queued, (first, second))
            },
        },
    )
    runtime.phase = "new_job_recovery"
    recovery_start = time.perf_counter()
    recovery = [
        submit(client, actor, question)
        for actor, question in zip((first, second), JOB_QUESTIONS[4:])
    ]
    wait_jobs(
        client,
        {ident: (actor, "complete") for ident, actor in zip(recovery, (first, second))},
    )
    recovery_ms = (time.perf_counter() - recovery_start) * 1000
    runtime.phase = "final_boundaries"
    for actor in runtime.actors:
        client.request(actor, "GET", "/api/auth/me")
        client.request(actor, "GET", "/api/v1/chats?limit=20")
    with runtime.storage.transaction() as conn:
        final = conn.execute(
            "SELECT count(*),count(*) FILTER(WHERE state='cancelled'),count(*) FILTER(WHERE state='complete'),count(*) FILTER(WHERE physical_until>clock_timestamp()) FROM app.analysis_jobs"
        ).fetchone()
    engine = runtime.engine.report()
    if (
        final != (6, 2, 4, 0)
        or (
            engine["started"],
            engine["completed"],
            engine["cancelled"],
            engine["physical_fake_active"],
            engine["maximum_physical_fake_active"],
        )
        != (6, 4, 2, 0, 2)
        or runtime.provider_attempts
    ):
        raise ValueError("mixed_analysis_final_boundaries_failed")
    return {
        "mixed_reads": reads,
        "engine": engine,
        "recovery_pair_ms": round(recovery_ms, 4),
        "streams": {
            "connections": client.streams,
            "metadata_events_read": client.stream_events,
            "bytes_read": client.stream_bytes,
            "slow_reader_connections": 1,
            "client_disconnects": 2,
            "durable_leases_after_disconnect": 0,
            "network_backpressure_saturation_tested": False,
        },
        "http": meter.report(),
    }
