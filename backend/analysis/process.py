"""A killable local process contains stalls; capacity is released after reap only."""

import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import threading
import time
from analysis.policy import MAX_FRAME_BYTES
from analysis.child_payload import payload
from analysis.engine import Control
from analysis.process_io import Unreaped, RemoteUncertain, write, reap

__all__ = ["ProcessEngine", "payload", "Unreaped", "RemoteUncertain", "reap"]


class ProcessEngine:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.children = set()
        self.stop_lock = threading.Lock()
        self.remote_uncertain = set()
        self.active_runs = set()
        self.closed = False

    def run(self, data: dict, control: Control) -> tuple[dict, int]:
        encoded = (
            json.dumps(
                data, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode()
            + b"\n"
        )
        if len(encoded) > 65536:
            raise ValueError("analysis_input_bound")
        with self.lock:
            if self.closed:
                raise RuntimeError("analysis_stopped")
            deadline = time.monotonic() + data["remaining_seconds"]
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-s",
                    "-u",
                    "-m",
                    "analysis.child",
                    str(os.getpid()),
                    str(deadline),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
                start_new_session=True,
                cwd=Path(__file__).resolve().parents[1],
                env={
                    "PATH": os.defpath,
                    "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONNOUSERSITE": "1",
                },
            )
            self.children.add(process)
            self.active_runs.add(process)
        selector = selectors.DefaultSelector()
        result = None
        buffer = b""
        last_check = 0.0
        try:
            control(None)
            write(process, encoded, control, deadline)
            selector.register(process.stdout, selectors.EVENT_READ)
            until = deadline + 1
            while time.monotonic() < until:
                instant = time.monotonic()
                if instant - last_check >= 0.8:
                    control(None)
                    last_check = instant
                ready = selector.select(0.1)
                if not ready:
                    if process.poll() is not None:
                        break
                    continue
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    break
                buffer += chunk
                if len(buffer) > MAX_FRAME_BYTES:
                    raise ValueError("analysis_output_bound")
                while b"\n" in buffer:
                    frame, buffer = buffer.split(b"\n", 1)
                    message = json.loads(frame)
                    if (
                        message.get("kind") == "stage"
                        and set(message) == {"kind", "stage"}
                        and len(frame) <= 512
                    ):
                        control(message["stage"])
                        write(process, b"go\n", control, deadline)
                    elif (
                        message.get("kind") == "result"
                        and set(message) == {"kind", "response", "http_status"}
                        and result is None
                    ):
                        result = (message["response"], message["http_status"])
                    else:
                        raise ValueError("analysis_protocol_invalid")
            process.wait(timeout=2)
            if process.returncode != 0 or result is None or buffer:
                raise RuntimeError("analysis_child_failed")
            return result
        finally:
            confirmed = False
            remote_safe = True
            original = sys.exc_info()[1]
            try:
                remote_safe = self._stop(process)
                confirmed = True
            finally:
                selector.close()
                process.stdin.close()
                process.stdout.close()
                with self.lock:
                    self.active_runs.discard(process)
                    if confirmed:
                        self.children.discard(process)
                        self.remote_uncertain.discard(process)
            if not remote_safe:
                raise RemoteUncertain(
                    getattr(original, "state", "interrupted")
                ) from None

    def _stop(self, process: subprocess.Popen) -> bool:
        # Concurrent shutdown and worker-finally must share the same uncertainty
        # result, even when the second observer sees an already-dead process.
        with self.stop_lock:
            safe = reap(process)
            with self.lock:
                if not safe:
                    self.remote_uncertain.add(process)
                return process not in self.remote_uncertain

    def close(self) -> None:
        with self.lock:
            self.closed = True
            children = tuple(self.children)
        for process in children:
            self._stop(process)
            with self.lock:
                self.children.discard(process)
                if process not in self.active_runs:
                    self.remote_uncertain.discard(process)
