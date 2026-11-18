"""Offline executable fixture; production never selects this launcher."""

import json
import os
import resource
import signal
import sys
import time
from analysis.child import contain, notify
from analysis.policy import MAX_FRAME_BYTES

deadline = float(sys.argv[2])
if len(sys.argv) > 3 and sys.argv[3] == "stop-before-bootstrap":
    os.kill(os.getpid(), signal.SIGSTOP)
contain(int(sys.argv[1]), deadline - time.monotonic())
payload = json.loads(sys.stdin.buffer.readline(65537))
notify("generating")
mode = payload["question"]
if mode == "hold":
    time.sleep(20)
elif mode in {"oversize-interruptible", "oversize-ignore-interrupt"}:
    # Fix the offline child's signal disposition before the parent can see
    # an oversized frame. Neither mode contacts an upstream service.
    disposition = signal.SIG_DFL if mode == "oversize-interruptible" else signal.SIG_IGN
    signal.signal(signal.SIGINT, disposition)
    pending = memoryview(b"x" * (MAX_FRAME_BYTES + 1))
    while pending:
        written = os.write(sys.stdout.fileno(), pending)
        pending = pending[written:]
    signal.pause()
else:
    response = {
        "status": "success",
        "sql": "SELECT 7",
        "model": "offline-fixture",
        "message": "bounded",
        "tables": [],
        "visualizations": [],
        "kpis": [],
        "error": None,
    }
    response["fixture"] = {
        "pid": os.getpid(),
        "group": os.getpgrp(),
        "parent": os.getppid(),
        "address_limit": resource.getrlimit(resource.RLIMIT_AS)[0],
        "cpu_limit": resource.getrlimit(resource.RLIMIT_CPU)[0],
        "file_limit": resource.getrlimit(resource.RLIMIT_FSIZE)[0],
        "descriptor_limit": resource.getrlimit(resource.RLIMIT_NOFILE)[0],
        "app_secret_present": any(
            key in os.environ
            for key in [
                "APP_DATABASE_URL",
                "SESSION_SECRET",
                "RESEND_API_KEY",
                "ACCOUNT_MAIL_OUTBOX_KEY",
            ]
        ),
    }
    print(
        json.dumps({"kind": "result", "response": response, "http_status": 200}),
        flush=True,
    )
