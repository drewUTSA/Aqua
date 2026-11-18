"""An uncertain local kill must retain both process tracking and durable capacity."""

from pathlib import Path
import subprocess
from uuid import uuid4

import pytest

from analysis.dispatch import Halt
from analysis.process import ProcessEngine, RemoteUncertain, Unreaped, payload
from nl2sql.config import Settings
from workspace.contracts import FirstSubmission


def test_unreaped_failure_never_refunds_physical_execution_reservation(security):
    assert_interrupted_reservation(
        security,
        Unreaped("private process failure must not be reflected"),
        quarantined=True,
    )


def test_remote_uncertain_retains_a_finite_physical_reservation(security):
    assert_interrupted_reservation(
        security, RemoteUncertain("interrupted"), quarantined=False
    )


def assert_interrupted_reservation(security, failure, *, quarantined):
    service = security.service()
    _, session = security.session()
    saved, _ = service.enqueue(session, FirstSubmission(**security.world.body()))

    def uncertain():
        raise failure

    security.engine.hook = uncertain
    assert service.tick()
    with security.storage.transaction() as conn:
        assert conn.execute(
            "SELECT state,physical_until>clock_timestamp(),"
            "physical_until>='9999-01-01T00:00:00Z',question,context,content_bytes "
            "FROM app.analysis_jobs WHERE id=%s",
            (saved["request"]["id"],),
        ).fetchone() == ("interrupted", True, quarantined, "", [], 0)
        assert conn.execute("SELECT count(*) FROM app.visual_results").fetchone() == (
            0,
        )


def test_real_uncertain_child_remains_tracked_until_retry_reap_confirms_exit(
    monkeypatch,
):
    import analysis.process as process_module

    actual_spawn, actual_reap = subprocess.Popen, process_module.reap
    observed = []

    def spawn(arguments, **options):
        index = arguments.index("-m")
        fixed = [
            *arguments[:index],
            str(Path(__file__).with_name("analysis_process_child.py")),
            *arguments[index + 2 :],
        ]
        child = actual_spawn(fixed, **options)
        observed.append(child)
        return child

    def uncertain(child):
        raise Unreaped("injected confirmation failure, no raw child output")

    def cancel(stage):
        if stage == "generating":
            raise Halt("cancelled")

    monkeypatch.setattr(process_module.subprocess, "Popen", spawn)
    monkeypatch.setattr(process_module, "reap", uncertain)
    job = {
        "user_id": str(uuid4()),
        "request_id": str(uuid4()),
        "model": "ollama",
        "grant_version": 1,
        "auth_epoch": 0,
        "context": [],
        "context_digest": bytes(32),
    }
    engine = ProcessEngine()
    try:
        with pytest.raises(Unreaped):
            engine.run(payload(job, "hold", Settings(), 3), cancel)
        assert len(observed) == 1 and observed[0] in engine.children
        with pytest.raises(Unreaped):
            engine.close()
        assert observed[0] in engine.children
        monkeypatch.setattr(process_module, "reap", actual_reap)
        engine.close()
        assert observed[0].poll() is not None
    finally:
        for child in observed:
            actual_reap(child)
