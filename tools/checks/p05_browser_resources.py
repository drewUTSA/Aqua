"""Own only run-specific synthetic containers and a tmpfs socket volume."""

import re
import subprocess
import time
from typing import Any

from app_fixture import initialize
from p05_browser_docker import ROOT, create, docker, owned_resource, source_archive
from p05_browser_protocol import MAX_SECONDS, POSTGRES


def wait_for_postgres(pg: str) -> None:
    """Wait for the final postmaster, never initdb's temporary socket server.

    The pinned image starts a socket-only temporary server while PID 1 is still
    its entrypoint shell. Accepting that socket races the entrypoint's shutdown.
    Only the final ``exec postgres`` makes postgres PID 1. Keep TCP disabled and
    check the private socket only after that transition, within one deadline.
    """
    deadline = time.monotonic() + 45
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("fixture_postgres_unavailable")
        try:
            process = docker(
                "exec", pg, "cat", "/proc/1/comm", timeout=min(5, remaining)
            )
            remaining = deadline - time.monotonic()
            if process == b"postgres\n" and remaining > 0:
                docker(
                    "exec",
                    pg,
                    "pg_isready",
                    "-h",
                    "/run/aqua-app-db",
                    "-U",
                    "postgres",
                    timeout=min(5, remaining),
                )
                if time.monotonic() < deadline:
                    return
        except (RuntimeError, subprocess.TimeoutExpired):
            pass  # Startup/restart errors may recover, but never extend the bound.
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("fixture_postgres_unavailable")
        time.sleep(min(0.5, remaining))


class Resources:
    def __init__(self, name: str) -> None:
        if not re.fullmatch(r"aqua-p05-browser-[a-f0-9]{24}", name):
            raise ValueError("fixture_run_scope_invalid")
        self.name = name
        self.volume = name + "-socket"
        self.attempted: list[tuple[str, str]] = []
        self.uncertain: set[str] = set()

    def preparing(self, kind: str, name: str) -> None:
        # Record before asking the daemon: a lost response may still create it.
        self.attempted.append((kind, name))
        self.uncertain.add(name)

    def provision(self, image: str, report: dict[str, Any]) -> str:
        name, volume = self.name, self.volume
        report["step"] = "images"
        for candidate in (image, POSTGRES):
            if not re.fullmatch(
                r"sha256:[a-f0-9]{64}",
                docker("image", "inspect", candidate, "--format", "{{.Id}}")
                .decode()
                .strip(),
            ):
                raise RuntimeError("fixture_image_unavailable")
        report["step"] = "socket_volume"
        self.preparing("volume", volume)
        docker(
            "volume",
            "create",
            "--label",
            "io.aqua.purpose=p05-browser-fixture",
            "--label",
            "io.aqua.run=" + name,
            "--driver=local",
            "--opt=type=tmpfs",
            "--opt=device=tmpfs",
            "--opt=o=size=16m,uid=999,gid=999,mode=0777",
            volume,
        )
        self.uncertain.discard(volume)
        report["step"] = "postgres_create"
        self.preparing("container", name + "-pg")
        pg = create(
            name + "-pg",
            POSTGRES,
            "--user=999:999",
            "--tmpfs=/var/lib/postgresql/data:rw,nosuid,nodev,size=536870912,uid=999,gid=999,mode=0700",
            "--tmpfs=/var/run/postgresql:rw,nosuid,nodev,size=16777216,uid=999,gid=999",
            "--tmpfs=/tmp:rw,nosuid,nodev,size=67108864",
            "--mount",
            f"type=volume,source={volume},target=/run/aqua-app-db",
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            command=(
                "postgres",
                "-c",
                "listen_addresses=",
                "-c",
                "unix_socket_directories=/var/run/postgresql,/run/aqua-app-db",
            ),
        )
        self.uncertain.discard(name + "-pg")
        docker("start", pg)
        report["step"] = "postgres_ready"
        wait_for_postgres(pg)
        docker(
            "exec",
            "-i",
            pg,
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            data=b"CREATE ROLE nl2sql_reader LOGIN; CREATE DATABASE aqua_test_bank; CREATE DATABASE aqua_test_pagila;",
        )
        report["step"] = "app_roles"
        initialize(docker, pg, ROOT)
        hba = b"local all postgres peer\nlocal aqua_app aqua_app_runtime scram-sha-256\nlocal aqua_app aqua_app_migrator scram-sha-256\nlocal all all reject\nhost all all 0.0.0.0/0 reject\nhost all all ::/0 reject\n"
        docker(
            "exec", "-i", pg, "tee", "/var/lib/postgresql/data/pg_hba.conf", data=hba
        )
        docker(
            "exec", pg, "psql", "-X", "-U", "postgres", "-c", "SELECT pg_reload_conf()"
        )
        report["step"] = "worker_create"
        self.preparing("container", name + "-api")
        runner = create(
            name + "-api",
            image,
            "--user=1000:1000",
            "--tmpfs=/tmp:rw,nosuid,nodev,size=134217728,mode=1777",
            "--tmpfs=/checks:rw,nosuid,nodev,size=67108864,mode=0777",
            "--mount",
            f"type=volume,source={volume},target=/run/aqua-app-db,readonly",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-e",
            "PYTHON_DOTENV_DISABLED=1",
            "--workdir=/tmp",
            "--entrypoint=/bin/sleep",
            command=(str(MAX_SECONDS),),
        )
        self.uncertain.discard(name + "-api")
        docker("start", runner)
        unpack = "import io,sys,tarfile;tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read())).extractall('/checks',filter='data')"
        report["step"] = "source_copy"
        docker("exec", "-i", runner, "python", "-c", unpack, data=source_archive())
        return runner

    def cleanup(self) -> list[str]:
        """Clean exact owned names, including creates whose response was lost."""
        remaining = []
        for kind, name in reversed(self.attempted):
            try:
                identifier = owned_resource(kind, name, self.name)
                if identifier is None:
                    # A timed-out daemon request may still finish later. If no
                    # owned object can be resolved, report uncertainty honestly.
                    if name in self.uncertain:
                        remaining.append(name)
                    continue
                try:
                    if kind == "container":
                        docker("rm", "--force", identifier, timeout=15)
                    else:
                        docker("volume", "rm", identifier, timeout=15)
                except (RuntimeError, OSError, subprocess.TimeoutExpired):
                    pass  # A lost remove response also needs an absence check.
                if owned_resource(kind, name, self.name) is not None:
                    remaining.append(name)
            except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired):
                remaining.append(name)
        return remaining
