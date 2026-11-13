"""Measure synthetic private history and metadata; never read deployment config."""

from concurrent.futures import ThreadPoolExecutor
import json
import math
import platform
import threading
import time
from types import SimpleNamespace

import psycopg
from nl2sql.schema import load_schema
from storage.config import StorageSettings
from storage.migrate import apply
from storage.pool import Storage, StorageUnavailable
from workspace.history import list_chats

DSN = (
    "postgresql://aqua_app_runtime:fixture-only@127.0.0.1:5432/aqua_app?sslmode=disable"
)
SECRET = "synthetic-capacity-only-secret-32-bytes"


def samples(function, count: int = 30) -> dict:
    """Nearest-rank percentiles; thirty samples cannot support p99 claims."""
    values = []
    for _ in range(count):
        started = time.perf_counter()
        function()
        values.append((time.perf_counter() - started) * 1000)
    values.sort()
    return {
        "samples": count,
        "p50_ms": round(values[math.ceil(count * 0.5) - 1], 4),
        "p95_ms": round(values[math.ceil(count * 0.95) - 1], 4),
        "max_ms": round(values[-1], 4),
    }


def private_history() -> dict:
    """Exercise production keyset code on one large and one hundred small owners."""
    with psycopg.connect(DSN.replace("runtime", "migrator"), autocommit=True) as conn:
        assert apply(conn) == 9
    with psycopg.connect(DSN, autocommit=True) as conn:
        owner = conn.execute(
            "INSERT INTO app.users(status) VALUES('active') RETURNING id"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO app.chats(user_id,title,last_activity_at) SELECT %s,'History '||n,"
            "'2026-01-01'::timestamptz+n*interval '1 second' FROM generate_series(1,10000) n",
            (owner,),
        )
        conn.execute(
            "WITH owners AS (INSERT INTO app.users(status) SELECT 'active' FROM generate_series(1,100) RETURNING id) "
            "INSERT INTO app.chats(user_id,title) SELECT id,'Small '||n FROM owners CROSS JOIN generate_series(1,20) n"
        )
        session = SimpleNamespace(user={"id": str(owner)})

        def page(cursor=None):
            return list_chats(
                conn,
                session,
                SECRET,
                limit=100,
                cursor=cursor,
                search="",
                archived=False,
                project_id=None,
            )

        first = page()
        cursor, seen = first["next_cursor"], {item["id"] for item in first["items"]}
        for _ in range(98):
            result = page(cursor)
            assert not (seen & {item["id"] for item in result["items"]})
            seen.update(item["id"] for item in result["items"])
            cursor = result["next_cursor"]
        assert len(seen) == 9900 and cursor
        deep = page(cursor)
        assert len(deep["items"]) == 100 and deep["next_cursor"] is None
        assert not (seen & {item["id"] for item in deep["items"]})
        first_timing = samples(page)
        deep_timing = samples(lambda: page(cursor))
        boundary = deep["items"][0]
        sql = (
            "SELECT id,title FROM app.chats WHERE user_id=%s AND NOT archived AND deleted_at IS NULL "
            "AND history_generation=(SELECT history_generation FROM app.users WHERE id=%s) "
            "AND (last_activity_at,id)<(%s::timestamptz,%s::uuid) "
            "ORDER BY last_activity_at DESC,id DESC LIMIT 101"
        )
        plan = conn.execute(
            "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + sql,
            (owner, owner, boundary["last_activity_at"], boundary["id"]),
        ).fetchone()[0][0]
        return {
            "large_owner_chats": 10000,
            "small_owners": 100,
            "small_owner_chats": 20,
            "page_size": 100,
            "first_page": first_timing,
            "page_100": deep_timing,
            "unique_traversed": len(seen) + len(deep["items"]),
            "deep_plan": plan,
        }


def metadata() -> dict:
    """Separate first load and repeat same-connection catalog loads; no row sampling."""
    result = {}
    for dataset in ("bank", "pagila"):
        with psycopg.connect(
            f"postgresql://nl2sql_reader@127.0.0.1/aqua_test_{dataset}", autocommit=True
        ) as conn:
            started = time.perf_counter()
            schema = load_schema(conn)
            result[dataset] = {
                "tables": len(schema.tables),
                "first_load_ms": round((time.perf_counter() - started) * 1000, 4),
                "warm_catalog": samples(lambda: load_schema(conn)),
            }
    return result


def pool_limits() -> dict:
    """Measure bounded overload rejection and normal recovery without tuning policy."""
    service = Storage(StorageSettings(True, DSN, 1, 1, 0.2))
    entered, release = threading.Event(), threading.Event()

    def hold():
        with service.transaction():
            entered.set()
            assert release.wait(3)

    def ordinary():
        with service.transaction() as conn:
            assert conn.execute("SELECT 1").fetchone() == (1,)

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            holder = workers.submit(hold)
            assert entered.wait(2)
            waiter = workers.submit(ordinary)
            deadline = time.monotonic() + 1
            while service._pool.get_stats().get("requests_waiting", 0) < 1:
                assert time.monotonic() < deadline
                time.sleep(0.002)
            started = time.perf_counter()
            try:
                ordinary()
            except StorageUnavailable:
                reject_ms = (time.perf_counter() - started) * 1000
            else:
                raise AssertionError("unbounded_pool_admission")
            finally:
                release.set()
            holder.result()
            waiter.result()
        recovery = samples(ordinary)
        assert service.readiness()["status"] == "ready"
        return {
            "connections": 1,
            "waiting": 1,
            "wait_seconds": 0.2,
            "overflow_rejected_ms": round(reject_ms, 4),
            "recovery": recovery,
        }
    finally:
        release.set()
        service.close()


if __name__ == "__main__":
    print(
        json.dumps(
            {
                "status": "passed",
                "python": platform.python_version(),
                "scope": "networkless disposable synthetic databases; no providers",
                "history": private_history(),
                "metadata": metadata(),
                "pool": pool_limits(),
            },
            sort_keys=True,
        )
    )
