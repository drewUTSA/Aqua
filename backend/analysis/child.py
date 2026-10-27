"""Bootstrap resource/death limits before loading analytical libraries or secrets."""

import ctypes
import json
import os
import resource
import signal
import sys
import time


def contain(parent: int, seconds: float) -> None:
    if sys.platform != "linux" or not 0 < seconds <= 120:
        raise RuntimeError("analysis_platform_invalid")
    # Default SIGALRM terminates even while native SDK code holds Python's GIL.
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.default_int_handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    if (
        ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL, 0, 0, 0) != 0
        or os.getppid() != parent
    ):
        os._exit(70)
    for name, limit in [
        (resource.RLIMIT_AS, 768 * 1024 * 1024),
        (resource.RLIMIT_CPU, 30),
        (resource.RLIMIT_NOFILE, 64),
        (resource.RLIMIT_FSIZE, 0),
        (resource.RLIMIT_CORE, 0),
    ]:
        resource.setrlimit(name, (limit, limit))


def notify(stage: str) -> None:
    sys.stdout.write(
        json.dumps({"kind": "stage", "stage": stage}, separators=(",", ":")) + "\n"
    )
    sys.stdout.flush()
    if sys.stdin.buffer.readline(16) != b"go\n":
        raise RuntimeError("analysis_authority_lost")


def main() -> None:
    parent, deadline = int(sys.argv[1]), float(sys.argv[2])
    seconds = deadline - time.monotonic()
    contain(parent, seconds)
    raw = sys.stdin.buffer.readline(65537)
    if len(raw) > 65536 or not raw.endswith(b"\n"):
        raise ValueError("analysis_input_bound")
    data = json.loads(raw)
    from nl2sql.config import Settings
    from nl2sql.control import Budget, CURRENT
    from nl2sql.query_service import run

    budget = Budget(deadline, notify, data["context"], data["context_digest"])
    token = CURRENT.set(budget)
    try:
        response, status = run(
            data["question"],
            data["model"],
            Settings(**data["settings"]),
            data["principal"],
            data["grant_version"],
            data["auth_epoch"],
            include_metadata=data["workspace"],
        )
        encoded = json.dumps(
            {"kind": "result", "response": response, "http_status": status},
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode()
        if len(encoded) > 262143:
            raise ValueError("analysis_output_bound")
        sys.stdout.buffer.write(encoded + b"\n")
        sys.stdout.buffer.flush()
    finally:
        CURRENT.reset(token)


if __name__ == "__main__":
    main()
