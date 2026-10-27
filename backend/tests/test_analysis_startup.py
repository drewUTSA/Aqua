"""A readiness outage must preserve liveness and later resume persisted work."""

from dataclasses import replace
import time
from fastapi.testclient import TestClient
import main
from analysis.service import Analysis
from storage.pool import Storage, StorageUnavailable


def test_startup_storage_outage_preserves_health_and_resumes_queue(world, monkeypatch):
    account, _ = world.client()
    accepted = account.post("/api/v1/chats", json=world.body("Durable before restart"))
    assert accepted.status_code == 202
    request_id = accepted.json()["request"]["id"]
    storage = Storage(replace(world.storage.settings, max_connections=3, max_waiting=8))
    ready = storage.readiness
    unavailable = [True]

    def readiness():
        if unavailable[0]:
            raise StorageUnavailable("fixture_storage_unavailable")
        return ready()

    monkeypatch.setattr(storage, "readiness", readiness)
    service = Analysis(
        storage,
        world.policy,
        world.settings.session_secret,
        world.settings,
        engine=world.analysis.engine,
    )
    monkeypatch.setattr(main.app.state, "storage", storage)
    monkeypatch.setattr(main.app.state, "analysis", service)
    try:
        with TestClient(main.app) as client:
            assert client.get("/api/health").status_code == 200
            assert client.get("/api/ready").status_code == 503
            assert world.calls == []
            unavailable[0] = False
            until = time.monotonic() + 4
            while time.monotonic() < until:
                result = account.get("/api/v1/analysis-requests/" + request_id)
                if (
                    result.status_code == 200
                    and result.json()["request"]["state"] == "complete"
                ):
                    break
                time.sleep(0.05)
            else:
                raise AssertionError("durable_queue_did_not_resume")
            assert client.get("/api/ready").status_code == 200
            assert len(world.calls) == 1
    finally:
        service.close()
        storage.close()
