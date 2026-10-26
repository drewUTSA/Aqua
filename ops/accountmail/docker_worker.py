"""Bounded local Docker operations and verified owned-container cleanup."""

import json
from pathlib import Path
import re
import stat
import subprocess
import time

if __package__:
    from .private_env import Unavailable
else:
    from private_env import Unavailable

DOCKER = "/usr/bin/docker"
SOCKET = "/var/run/docker.sock"
IMAGE = "bank-ai-backend:latest"
NAME = "aqua-account-mail-worker"
PURPOSE = "account-mail-worker"
LABEL = "io.aqua.purpose"
RUN_LABEL = "io.aqua.run"
SOCKET_VOLUME = "aqua_app_sockets"
COMMAND_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/nonexistent",
    "DOCKER_CONFIG": "/nonexistent",
    "LANG": "C.UTF-8",
}
IDENT = re.compile(r"[a-f0-9]{64}\Z")


def host_ready() -> None:
    binary, endpoint = Path(DOCKER).stat(), Path(SOCKET).lstat()
    if (
        not stat.S_ISREG(binary.st_mode)
        or binary.st_uid != 0
        or binary.st_mode & 0o022
        or not stat.S_ISSOCK(endpoint.st_mode)
        or endpoint.st_uid != 0
    ):
        raise Unavailable("docker_unavailable")


class Docker:
    def __init__(self) -> None:
        self.deadline = time.monotonic() + 55

    def call(
        self,
        *args: str,
        timeout: float = 8,
        fd: int | None = None,
        cleanup: bool = False,
    ) -> str:
        remaining = 8 if cleanup else self.deadline - time.monotonic()
        if remaining <= 0:
            raise Unavailable("launcher_timeout")
        try:
            result = subprocess.run(
                [DOCKER, "--host=unix://" + SOCKET, "--config=/nonexistent", *args],
                capture_output=True,
                timeout=min(timeout, remaining),
                env=COMMAND_ENV,
                cwd="/",
                pass_fds=() if fd is None else (fd,),
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            raise Unavailable("docker_timeout") from None
        if result.returncode or len(result.stdout) > 65536:
            raise Unavailable("docker_command_failed")
        return result.stdout.decode("utf-8").strip()

    def ids(self, *filters: str, cleanup: bool = False) -> list[str]:
        args = ["container", "ls", "--all", "--no-trunc"]
        for value in filters:
            args += ["--filter", value]
        raw = self.call(*args, "--format", "{{.ID}}", cleanup=cleanup)
        values = raw.splitlines() if raw else []
        if len(values) > 64 or any(not IDENT.fullmatch(value) for value in values):
            raise Unavailable("unexpected_docker_response")
        return values

    def owned(self, nonce: str, *, cleanup: bool = False) -> str | None:
        ids = self.ids("name=^/" + NAME + "$", cleanup=cleanup)
        if not ids:
            return None
        if len(ids) != 1:
            raise Unavailable("worker_ownership_unconfirmed")
        raw = self.call(
            "container",
            "inspect",
            "--format",
            "{{.Id}}\n{{.Name}}\n{{json .Config.Labels}}",
            ids[0],
            cleanup=cleanup,
        )
        lines = raw.splitlines()
        if (
            len(lines) != 3
            or lines[:2] != [ids[0], "/" + NAME]
            or json.loads(lines[2]).get(LABEL) != PURPOSE
            or json.loads(lines[2]).get(RUN_LABEL) != nonce
        ):
            raise Unavailable("worker_ownership_unconfirmed")
        return ids[0]

    def clean(self, nonce: str, expected: str | None) -> bool:
        """Delete only this invocation's labelled ID and prove it is absent."""
        try:
            ident = self.owned(nonce, cleanup=True)
            if ident is None:
                # A timed-out create without an observed ID remains uncertain.
                return expected is not None and not self.ids(
                    "id=" + expected, cleanup=True
                )
            if expected is not None and ident != expected:
                return False
            try:
                self.call("container", "rm", "--force", ident, cleanup=True)
            except Unavailable:
                pass  # A lost response is resolved by the independent absence check.
            return not self.ids("id=" + ident, cleanup=True)
        except Exception:
            return False
