"""Operator binary stream for encrypted off-server backup; never run into chat."""

import subprocess
import sys
import threading

from private import credentials

CONTAINER = "aqua-app-db"


def main() -> None:
    if sys.stdout.isatty():
        raise RuntimeError(
            "pipe binary output directly to the approved encrypted backup client"
        )
    secret = credentials()["backup"]
    # Password arrives over stdin, not argv; stdout is only pg_dump binary data.
    command = [
        "/usr/bin/docker",
        "exec",
        "-i",
        CONTAINER,
        "sh",
        "-c",
        "IFS= read -r PGPASSWORD; export PGPASSWORD; exec pg_dump -h /var/run/postgresql -U aqua_app_backup -d aqua_app -Fc --no-owner",
    ]
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    timer = threading.Timer(
        120, lambda: process.kill() if process.poll() is None else None
    )
    timer.start()
    try:
        assert process.stdin and process.stdout
        process.stdin.write(secret.encode() + b"\n")
        process.stdin.close()
        total = 0
        while chunk := process.stdout.read(65536):
            total += len(chunk)
            if total > 512 * 1024 * 1024:
                raise RuntimeError("initial_backup_size_budget_exceeded")
            sys.stdout.buffer.write(chunk)
        if process.wait(timeout=120):
            raise RuntimeError("backup_export_failed_output_redacted")
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
