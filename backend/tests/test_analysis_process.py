"""Real Linux processes prove termination, clean credentials and bounded IPC."""

from pathlib import Path
import subprocess
import time
import os
import signal
import sys
import json
import pytest
from analysis.dispatch import Halt
from analysis.process import ProcessEngine, payload, RemoteUncertain
from nl2sql.config import Settings


def launch(monkeypatch, before_read=False):
    actual = subprocess.Popen
    seen = []

    def create(arguments, **options):
        index = arguments.index("-m")
        arguments = [
            *arguments[:index],
            str(Path(__file__).with_name("analysis_process_child.py")),
            *arguments[index + 2 :],
        ]
        if before_read:
            arguments.append("stop-before-bootstrap")
            options["pipesize"] = 4096
        process = actual(arguments, **options)
        seen.append((process, options["env"]))
        return process

    monkeypatch.setattr("analysis.process.subprocess.Popen", create)
    return seen


def data(question, seconds=3):
    from uuid import uuid4

    job = {
        "user_id": str(uuid4()),
        "request_id": str(uuid4()),
        "model": "ollama",
        "grant_version": 1,
        "auth_epoch": 0,
        "context": [],
        "context_digest": bytes(32),
    }
    return payload(
        job,
        question,
        Settings(
            session_secret="NEVER_PASS_SESSION",
            indexer_database_url="NEVER_PASS_INDEXER",
        ),
        seconds,
    )


def test_real_child_limits_and_credentials(monkeypatch):
    monkeypatch.setenv("APP_DATABASE_URL", "NEVER_PASS_APPLICATION_WRITER")
    monkeypatch.setenv("RESEND_API_KEY", "NEVER_PASS_MAIL")
    seen = launch(monkeypatch)
    response, status = ProcessEngine().run(data("limits"), lambda stage: None)
    assert status == 200
    info = response["fixture"]
    assert info["group"] == info["pid"] and info["parent"] != info["pid"]
    assert (
        info["address_limit"],
        info["cpu_limit"],
        info["file_limit"],
        info["descriptor_limit"],
    ) == (768 * 1024 * 1024, 30, 0, 64)
    assert info["app_secret_present"] is False
    assert seen[0][0].poll() == 0
    assert "APP_DATABASE_URL" not in seen[0][1]
    encoded = str(data("limits"))
    assert all(
        secret not in encoded
        for secret in [
            "NEVER_PASS_SESSION",
            "NEVER_PASS_INDEXER",
            "NEVER_PASS_APPLICATION_WRITER",
            "NEVER_PASS_MAIL",
        ]
    )


def test_real_cancel_reaps_the_owned_process(monkeypatch):
    seen = launch(monkeypatch)

    def cancel(stage):
        if stage == "generating":
            raise Halt("cancelled")

    with pytest.raises(Halt):
        ProcessEngine().run(data("hold"), cancel)
    assert seen[0][0].poll() is not None


def test_real_child_hard_deadline_and_oversize_reap(monkeypatch):
    seen = launch(monkeypatch)
    start = time.monotonic()
    with pytest.raises(RuntimeError):
        ProcessEngine().run(data("hold", 0.35), lambda stage: None)
    assert time.monotonic() - start < 2
    assert seen[-1][0].poll() is not None
    with pytest.raises(ValueError, match="analysis_output_bound"):
        ProcessEngine().run(data("oversize"), lambda stage: None)
    assert seen[-1][0].poll() is not None


def test_parent_death_stops_child_independently_of_python_cleanup():
    helper = Path(__file__).with_name("analysis_process_parent.py")
    parent = subprocess.Popen(
        [sys.executable, "-u", str(helper)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={
            "PATH": os.defpath,
            "PYTHONPATH": str(helper.parents[1]),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        start_new_session=True,
    )
    child = None
    try:
        child = json.loads(parent.stdout.readline())["child_pid"]
        # Let the child finish its PR_SET_PDEATHSIG/parent-PID bootstrap.
        time.sleep(0.2)
        parent.kill()
        parent.wait(timeout=2)
        until = time.monotonic() + 2
        while time.monotonic() < until:
            status = Path(f"/proc/{child}/stat")
            if not status.exists() or status.read_text().split()[2] == "Z":
                break
            time.sleep(0.02)
        else:
            raise AssertionError("child_survived_parent_death")
        status = Path(f"/proc/{child}/status")
        if status.exists():
            # The kernel closes zombie descriptors; /proc/PID/fd is correctly
            # inaccessible to this cap-drop fixture, so inspect safe status.
            assert "FDSize:\t0" in status.read_text()
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=2)
        parent.stdout.close()
        if child is not None:
            command = Path(f"/proc/{child}/cmdline")
            if (
                command.exists()
                and b"analysis_process_child.py" in command.read_bytes()
            ):
                try:
                    os.killpg(child, signal.SIGKILL)
                except ProcessLookupError:
                    pass


@pytest.mark.parametrize("cancel", [False, True])
def test_bootstrap_pipe_stall_still_obeys_deadline_and_cancellation(
    monkeypatch, cancel
):
    seen = launch(monkeypatch, before_read=True)
    input_data = data("hold", 1 if cancel else 0.35)
    input_data["context"] = [{"question": "x" * 16000}]
    started = time.monotonic()

    def control(stage):
        if cancel and time.monotonic() - started > 0.2:
            raise Halt("cancelled")

    with pytest.raises((RemoteUncertain, Halt)):
        ProcessEngine().run(input_data, control)
    assert time.monotonic() - started < 3
    assert seen[-1][0].poll() is not None
