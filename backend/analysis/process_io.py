"""Pipe writes and process stopping have deadlines even before child bootstrap."""

from collections.abc import Callable
import os
import select
import signal
import subprocess
import time


class Unreaped(RuntimeError):
    """Unconfirmed local death quarantines its durable physical reservation."""


class RemoteUncertain(RuntimeError):
    """The local child died, but upstream SQL cancellation was not confirmed."""

    def __init__(self, state: str) -> None:
        self.state = (
            state if state in {"cancelled", "expired", "interrupted"} else "interrupted"
        )


def write(
    process: subprocess.Popen,
    data: bytes,
    control: Callable[[str | None], None],
    deadline: float,
) -> None:
    descriptor = process.stdin.fileno()
    os.set_blocking(descriptor, False)
    position = 0
    last_check = 0.0
    while position < len(data):
        instant = time.monotonic()
        if instant >= deadline:
            raise RuntimeError("analysis_pipe_deadline")
        if instant - last_check >= 0.2:
            control(None)
            last_check = instant
        if not select.select([], [descriptor], [], min(0.1, deadline - instant))[1]:
            continue
        try:
            position += os.write(descriptor, data[position : position + 4096])
        except BlockingIOError:
            continue


def reap(process: subprocess.Popen) -> bool:
    """SIGINT lets psycopg cancel and consume QueryCanceled before process exit."""
    if process.poll() is not None:
        return process.returncode not in {-signal.SIGALRM, -signal.SIGKILL}
    try:
        os.killpg(process.pid, signal.SIGINT)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=1.5)
        return process.returncode not in {-signal.SIGALRM, -signal.SIGKILL}
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        raise Unreaped("analysis_exit_unconfirmed") from None
    return False
