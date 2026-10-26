"""Linux operator launcher: one isolated account-mail job, never a web thread."""

import json
from pathlib import Path
import re
import secrets
import signal
import sys

if __package__:
    from .docker_worker import (
        Docker,
        host_ready,
        IMAGE,
        NAME,
        PURPOSE,
        LABEL,
        RUN_LABEL,
        SOCKET_VOLUME,
        IDENT,
    )
    from .private_env import (
        PRIVATE,
        Unavailable,
        private_directory,
        read_environment,
        sealed_environment,
        singleton,
    )
else:
    from docker_worker import (
        Docker,
        host_ready,
        IMAGE,
        NAME,
        PURPOSE,
        LABEL,
        RUN_LABEL,
        SOCKET_VOLUME,
        IDENT,
    )
    from private_env import (
        PRIVATE,
        Unavailable,
        private_directory,
        read_environment,
        sealed_environment,
        singleton,
    )


def launch(directory: Path = PRIVATE) -> str:
    private_directory(directory)
    with singleton(directory) as acquired:
        if not acquired:
            return "busy"
        raw, enabled = read_environment(directory)
        if not enabled:
            return "disabled"
        host_ready()
        docker = Docker()
        if docker.ids("label=" + LABEL + "=" + PURPOSE):
            raise Unavailable("leftover_worker")
        if docker.ids("name=^/" + NAME + "$"):
            raise Unavailable("leftover_worker")
        image = docker.call("image", "inspect", "--format", "{{.Id}}", IMAGE)
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
            raise Unavailable("image_unavailable")
        if (
            docker.call("volume", "inspect", "--format", "{{.Name}}", SOCKET_VOLUME)
            != SOCKET_VOLUME
        ):
            raise Unavailable("socket_volume_unavailable")
        nonce, ident = secrets.token_hex(16), None
        try:
            with sealed_environment(raw) as fd:
                ident = docker.call(
                    "container",
                    "create",
                    "--pull=never",
                    "--name",
                    NAME,
                    "--label",
                    LABEL + "=" + PURPOSE,
                    "--label",
                    RUN_LABEL + "=" + nonce,
                    "--network=bridge",
                    "--read-only",
                    "--cap-drop=ALL",
                    "--security-opt=no-new-privileges:true",
                    "--memory=128m",
                    "--memory-swap=128m",
                    "--cpus=1",
                    "--pids-limit=32",
                    "--user=1000:1000",
                    "--restart=no",
                    "--log-driver=none",
                    "--no-healthcheck",
                    "--stop-timeout=5",
                    "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=8388608",
                    "--mount",
                    "type=volume,src="
                    + SOCKET_VOLUME
                    + ",dst=/run/aqua-app-db,readonly",
                    "--env-file",
                    "/proc/self/fd/" + str(fd),
                    "--env=PYTHON_DOTENV_DISABLED=1",
                    "--env=PYTHONDONTWRITEBYTECODE=1",
                    "--entrypoint=python",
                    image,
                    "-m",
                    "auth.mailworker",
                    fd=fd,
                )
            if not IDENT.fullmatch(ident):
                ident = None
                raise Unavailable("unexpected_docker_response")
            if docker.owned(nonce) != ident:
                raise Unavailable("worker_ownership_unconfirmed")
            output = json.loads(
                docker.call("container", "start", "--attach", ident, timeout=35)
            )
            if output not in [{"status": "idle"}, {"status": "attempted"}]:
                raise Unavailable("unexpected_worker_response")
            return output["status"]
        finally:
            if not docker.clean(nonce, ident):
                raise Unavailable("cleanup_unconfirmed")


def _interrupted(signum: int, frame: object) -> None:
    raise Unavailable("interrupted")


def main() -> int:
    signal.signal(signal.SIGTERM, _interrupted)
    signal.signal(signal.SIGINT, _interrupted)
    try:
        status = launch()
    except Exception:
        # No exception/argv/child-output reflection, including unexpected errors.
        print(
            json.dumps(
                {"status": "unavailable", "detail": "account_mail_launcher_failed"}
            )
        )
        return 1
    print(json.dumps({"status": status}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
