"""Closed SSH transport injected into the production Ollama provider client seam."""

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import threading

from local_model_remote import validate


class BrokerStopped(RuntimeError):
    pass


class Broker:
    def __init__(self, digest, deadline):
        self.digest, self.deadline = digest, deadline
        self.calls, self.stopped, self.remote_exit_unknown = 0, False, False
        self.active = False
        self.responses = []
        self.lock = threading.Lock()
        self.source = Path(__file__).with_name("local_model_remote.py").read_bytes()
        if len(self.source) > 16384:
            raise BrokerStopped("remote_source_budget")
        self.remote_sha256 = hashlib.sha256(self.source).hexdigest()

    def send(self, body, case_deadline):
        if (
            self.stopped
            or self.active
            or self.calls >= 32
            or time.monotonic() >= min(self.deadline, case_deadline)
        ):
            raise BrokerStopped("experiment_stopped")
        validate({"digest": self.digest, "body": body})
        if not self.lock.acquire(blocking=False):
            raise BrokerStopped("concurrent_call_denied")
        self.active = True
        self.calls += 1
        script = base64.b64encode(self.source).decode()
        command = (
            "env -i PATH=/usr/bin:/bin /usr/bin/python3 -I -c 'import base64;exec(base64.b64decode(\""
            + script
            + "\"))'"
        )
        ssh = (
            r"C:\Windows\System32\OpenSSH\ssh.exe"
            if os.name == "nt"
            else "/usr/bin/ssh"
        )
        environment = (
            {
                "SystemRoot": os.environ.get("SystemRoot", r"C:\Windows"),
                "PROGRAMDATA": os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
            }
            if os.name == "nt"
            else {}
        )
        try:
            result = subprocess.run(
                [
                    ssh,
                    "-T",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "StrictHostKeyChecking=yes",
                    "-o",
                    "ConnectTimeout=5",
                    "aqua-codex",
                    command,
                ],
                input=json.dumps(
                    {"digest": self.digest, "body": body}, ensure_ascii=False
                ).encode(),
                capture_output=True,
                timeout=min(
                    45, max(0.01, min(self.deadline, case_deadline) - time.monotonic())
                ),
                env=environment,
            )
            if result.returncode or len(result.stdout) > 2200000:
                raise BrokerStopped("ssh_response_invalid")
            response = json.loads(result.stdout)
            if response.get("status") != "ok":
                raise BrokerStopped("remote_work_unverified")
            raw = response["body"].encode()
            if (
                len(raw) > 1048576
                or hashlib.sha256(raw).hexdigest() != response["response_sha256"]
            ):
                raise BrokerStopped("remote_response_invalid")
            value = json.loads(raw)
            if (
                type(value) is not dict
                or value.get("model") != "qwen3:4b"
                or value.get("done") is not True
            ):
                raise BrokerStopped("remote_model_completion_invalid")
            self.responses.append(response["response_sha256"])
            return raw
        except Exception as error:
            self.stopped = self.remote_exit_unknown = True
            raise BrokerStopped("broker_stopped_remote_exit_unknown") from error
        finally:
            self.active = False
            self.lock.release()
