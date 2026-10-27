"""Offline executable fixture; production never selects this launcher."""

import json
import os
import resource
import signal
import sys
import time
from analysis.child import contain, notify

deadline = float(sys.argv[2])
if len(sys.argv) > 3 and sys.argv[3] == "stop-before-bootstrap":
    os.kill(os.getpid(), signal.SIGSTOP)
contain(int(sys.argv[1]), deadline - time.monotonic())
payload = json.loads(sys.stdin.buffer.readline(65537))
notify("generating")
mode = payload["question"]
if mode == "hold":
    time.sleep(20)
elif mode == "oversize":
    sys.stdout.write("x" * 270000)
    sys.stdout.flush()
    time.sleep(20)
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
