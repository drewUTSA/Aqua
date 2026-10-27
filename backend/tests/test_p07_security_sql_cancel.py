"""Reaping local Python must also stop its already-running readonly SQL."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
from threading import Event
import time
from uuid import uuid4

import pytest

from analysis.dispatch import Halt
from analysis.process import ProcessEngine, payload
from nl2sql.config import load_settings
from nl2sql.db import connect


def test_real_process_cancel_stops_fixture_sql_before_capacity_can_be_released(
    live_database, monkeypatch
):
    settings = load_settings()
    assert settings.database_url == (
        f"postgresql://nl2sql_reader@127.0.0.1:5432/aqua_test_{live_database}"
    )
    nonce = uuid4().hex
    application = "aqua-p07-sql-cancel-" + nonce
    original = subprocess.Popen
    observed, cancel = [], Event()

    def spawn(arguments, **options):
        index = arguments.index("-m")
        fixed = [
            *arguments[:index],
            str(Path(__file__).with_name("p07_sql_cancel_child.py")),
            *arguments[index + 2 :],
        ]
        child = original(fixed, **options)
        observed.append(child)
        return child

    def control(stage):
        if cancel.is_set():
            raise Halt("cancelled")

    monkeypatch.setattr("analysis.process.subprocess.Popen", spawn)
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
    with connect(settings) as monitor:

        def activity():
            rows = monitor.execute(
                "SELECT pid,state FROM pg_stat_activity WHERE application_name=%s "
                "AND usename=current_user AND datname=current_database() "
                "AND pid<>pg_backend_pid()",
                (application,),
            ).fetchall()
            monitor.commit()  # A new stats snapshot is required for each poll.
            return rows

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(engine.run, payload(job, nonce, settings, 6), control)
            try:
                deadline = time.monotonic() + 3
                while not any(state == "active" for _, state in activity()):
                    assert not future.done() and time.monotonic() < deadline
                    time.sleep(0.02)
                started = time.monotonic()
                cancel.set()
                with pytest.raises(Halt):
                    future.result(timeout=4)
                assert time.monotonic() - started < 3
                assert len(observed) == 1 and observed[0].poll() is not None
                # This assertion runs before the dispatcher could release a slot.
                assert not any(state == "active" for _, state in activity())
            finally:
                cancel.set()
                try:
                    engine.close()
                finally:
                    # Even a failed proof must clean only its uniquely named
                    # fixture query; same-role control is never exposed by the app.
                    for pid, state in activity():
                        if state == "active":
                            monitor.execute("SELECT pg_cancel_backend(%s)", (pid,))
                            monitor.commit()
                    deadline = time.monotonic() + 2
                    while any(state == "active" for _, state in activity()):
                        assert time.monotonic() < deadline
                        time.sleep(0.02)
