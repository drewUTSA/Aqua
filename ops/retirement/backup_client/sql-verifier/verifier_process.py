"""Bounded subprocess pipes and cancellation; never infer container exit from CLI."""

import os
import selectors
import signal
import subprocess
import time

ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/proc/self/fd",
    "DOCKER_CONFIG": "/proc/self/fd",
}
DOCKER = ["/usr/bin/docker", "--host=unix:///var/run/docker.sock"]


class Failure(RuntimeError):
    pass


PROBE_STAGES = frozenset(
    {
        "bootstrap",
        "imports",
        "connections",
        "backup_slot",
        "chain",
        "privileges",
        "counts",
        "control",
        "events",
        "pages",
        "floors",
        "accounting",
    }
)
PROBE_CODES = frozenset(
    {
        "unclassified_failure",
        "verifier_backup_second_slot_not_proven",
        "verifier_backup_second_slot_admitted",
        "verifier_trusted_chain_mismatch",
        "verifier_signed_chain_link_invalid",
        "verifier_privilege_denial_not_proven",
        "verifier_unexpected_backup_privilege",
        "verifier_backup_role_invalid",
        "verifier_backup_durability_or_readonly_invalid",
        "verifier_backup_database_privileges_invalid",
        "verifier_six_table_inventory_invalid",
        "verifier_backup_table_privileges_invalid",
        "verifier_full_dump_count_mismatch",
        "verifier_control_or_pending_state_invalid",
        "verifier_event_batch_bound",
        "verifier_original_event_or_manifest_invalid",
        "verifier_all_signed_events_not_covered",
        "verifier_original_floors_or_fingerprints_mismatch",
        "verifier_original_manifest_accounting_mismatch",
    }
)


class Budget:
    def __init__(self, seconds):
        if not 0 < seconds <= 120:
            raise Failure("verifier_budget_invalid")
        self.until = time.monotonic() + seconds

    def remaining(self, maximum=30):
        seconds = min(maximum, self.until - time.monotonic())
        if seconds <= 0:
            raise Failure("verifier_deadline")
        return seconds


class Cancellation:
    def __enter__(self):
        self.cancelled = False
        self.cleaning = False
        self.previous = {}
        for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            self.previous[signum] = signal.getsignal(signum)
            signal.signal(signum, self.receive)
        return self

    def receive(self, signum, frame):
        first = not self.cancelled
        self.cancelled = True
        if first and not self.cleaning:
            raise Failure("verifier_cancelled")

    def __exit__(self, kind, value, traceback):
        for signum, handler in self.previous.items():
            signal.signal(signum, handler)


def bounded(argv, data=b"", *, seconds, maximum=65536):
    """No dump temp file, unbounded communicate buffer, stderr or command log."""
    if not 0 < seconds <= 120 or not 0 < maximum <= 1048576 or len(data) > 202375168:
        raise Failure("verifier_pipe_budget_invalid")
    process = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=ENV,
        start_new_session=True,
        bufsize=0,
    )
    deadline = time.monotonic() + seconds
    output, offset = bytearray(), 0
    try:
        for pipe in (process.stdin, process.stdout):
            os.set_blocking(pipe.fileno(), False)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            if data:
                selector.register(process.stdin, selectors.EVENT_WRITE)
            else:
                process.stdin.close()
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise Failure("verifier_pipe_deadline")
                for key, _ in selector.select(min(0.2, remaining)):
                    if key.fileobj is process.stdin:
                        try:
                            offset += os.write(
                                key.fd, memoryview(data)[offset : offset + 65536]
                            )
                        except BlockingIOError:
                            continue
                        if offset == len(data):
                            selector.unregister(process.stdin)
                            process.stdin.close()
                    else:
                        try:
                            part = os.read(key.fd, 65536)
                        except BlockingIOError:
                            continue
                        if not part:
                            selector.unregister(process.stdout)
                        else:
                            output.extend(part)
                            if len(output) > maximum:
                                raise Failure("verifier_pipe_output_bound")
        code = process.wait(timeout=max(0.01, deadline - time.monotonic()))
        return code, bytes(output)
    finally:
        try:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait(timeout=3)
        finally:
            process.stdin.close()
            process.stdout.close()


def docker(*args, data=b"", seconds=10, maximum=65536):
    code, output = bounded(DOCKER + list(args), data, seconds=seconds, maximum=maximum)
    if code:
        failure = (
            "verifier_restore_foreign_key_violation"
            if "pg_restore" in args and b"violates foreign key constraint" in output
            else "verifier_docker_failed"
        )
        raise Failure(failure)
    return output
