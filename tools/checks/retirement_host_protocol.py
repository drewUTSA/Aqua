"""Bounded native-fixture control and exact isolated-backend termination."""

import json
import os
import selectors
import signal
import subprocess
import sys
import time

import p05_browser_docker as commands
from retirement_host_resources import RUN


def lines(process, deadline: float, log: bytearray):
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    pending = bytearray()
    try:
        while process.poll() is None or selector.select(0):
            if time.monotonic() >= deadline:
                raise RuntimeError("native_fixture_process_deadline")
            if not selector.select(min(0.2, deadline - time.monotonic())):
                continue
            raw = os.read(process.stdout.fileno(), 65536)
            if not raw:
                break
            log.extend(raw)
            pending.extend(raw)
            if len(log) > 1024 * 1024:
                raise RuntimeError("native_fixture_output_capacity")
            while b"\n" in pending:
                line, _, pending = pending.partition(b"\n")
                yield line
        if pending:
            raise RuntimeError("native_fixture_incomplete_protocol_line")
    finally:
        selector.close()


def send(process, value: str) -> None:
    process.stdin.write(value.encode() + b"\n")
    process.stdin.flush()


def terminate_backend(resources, record: dict, role: str, suffix: str = "") -> None:
    if not RUN.fullmatch(resources.run) or role not in {
        "aqua_retirement_checkpoint",
        "aqua_app_runtime",
    }:
        raise RuntimeError("native_fixture_backend_scope_invalid")
    pid = record.get("pid")
    name = resources.run + suffix
    if (
        type(pid) is not int
        or not 1 < pid < 2**31
        or record.get("application_name") != name
    ):
        raise RuntimeError("native_fixture_backend_identity_invalid")
    database = "aqua_app" if role == "aqua_app_runtime" else "aqua_retirement"
    sql = f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE pid={pid} AND usename='{role}' AND datname='{database}' AND application_name='{name}'"
    result = commands.docker(
        "exec",
        resources.run + "-pg",
        "psql",
        "-X",
        "-U",
        "postgres",
        "-d",
        database,
        "-At",
        "-c",
        sql,
        timeout=10,
    )
    if result.strip() != b"t":
        raise RuntimeError("native_fixture_exact_backend_not_terminated")


def start(resources, role: str, processes: list):
    identifier = resources.create(role)
    resources.verify_layout()
    process = subprocess.Popen(
        [
            "/usr/bin/docker",
            "--host=unix:///var/run/docker.sock",
            "start",
            "--attach",
            "--interactive",
            identifier,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=commands.DOCKER_ENV,
        close_fds=True,
    )
    processes.append(process)
    return process


def role(resources, name: str, processes: list, log: bytearray) -> dict:
    process = start(resources, name, processes)
    result = None
    barrier = False
    for line in lines(process, time.monotonic() + 25, log):
        if line.startswith(b"{"):
            value = json.loads(line)
            if value.get("event") == "before_ACK":
                if name != "crash" or barrier:
                    raise RuntimeError("native_fixture_unexpected_ACK_barrier")
                barrier = True
                terminate_backend(resources, value, "aqua_retirement_checkpoint")
                send(process, "backend_terminated")
            else:
                result = value
    if process.wait(timeout=5) != 0 or result is None:
        raise RuntimeError("native_fixture_role_failed:" + name)
    if name == "crash" and (
        not barrier or result.get("status") != "expected_connection_death"
    ):
        raise RuntimeError("native_fixture_ACK_crash_not_proven")
    if not resources.remove(name):
        raise RuntimeError("native_fixture_role_exit_unconfirmed")
    return result


def mail(resources, root, processes: list, log: bytearray) -> dict:
    """Actual worker retains SH after both its PG session and host launcher die."""
    launcher = subprocess.Popen(
        [
            sys.executable,
            str(root / "tools/checks/retirement_fixture/native_mail.py"),
            "launcher",
            resources.run,
            str(resources.root / "mail"),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        close_fds=True,
        start_new_session=True,
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(root) + ":" + str(root / "backend"),
        },
    )
    processes.append(launcher)
    launcher_line = next(lines(launcher, time.monotonic() + 5, log))
    locked = json.loads(launcher_line)
    if locked.get("event") != "launcher_locked":
        raise RuntimeError("native_mail_launcher_not_locked")
    sender = start(resources, "mail", processes)
    checks = []
    probe = 0

    def exclusive(expected: bool):
        nonlocal probe
        value = role(resources, "web" + str(probe), processes, log)
        probe += 1
        if value.get("acquired") is not expected or (
            value.get("device"),
            value.get("inode"),
        ) != (locked["device"], locked["inode"]):
            raise RuntimeError("native_mail_EX_or_inode_mismatch")

    for line in lines(sender, time.monotonic() + 35, log):
        if not line.startswith(b"{"):
            continue
        value = json.loads(line)
        event = value.get("event")
        if event == "mail_sending":
            if checks or (value.get("device"), value.get("inode")) != (
                locked["device"],
                locked["inode"],
            ):
                raise RuntimeError("native_mail_worker_inode_mismatch")
            exclusive(False)
            terminate_backend(resources, value, "aqua_app_runtime", "-mail")
            exclusive(False)
            checks.append("actual_DB_backend_death_worker_SH_retained")
            send(sender, "verify_after_DB_death")
        elif event == "claim_survives_DB_death":
            if len(checks) != 1:
                raise RuntimeError("native_mail_protocol_order_invalid")
            launcher.kill()
            if launcher.wait(timeout=5) != -signal.SIGKILL:
                raise RuntimeError("native_mail_launcher_SIGKILL_not_observed")
            exclusive(False)
            checks.append("actual_launcher_SIGKILL_worker_SH_retained")
            send(sender, "verify_after_launcher_death")
        elif event == "claim_survives_launcher_death":
            if len(checks) != 2:
                raise RuntimeError("native_mail_protocol_order_invalid")
            send(sender, "finish_fake_send")
        elif value.get("status") == "expected_DB_loss_after_one_fake_send":
            if (
                not value.get("old_host_claim_rejected")
                or value.get("app_pool_max") != 1
                or value.get("fake_send_calls") != 1
            ):
                raise RuntimeError("native_mail_sender_boundary_failed")
            checks.append(
                "actual_MailWorker_single_slot_one_fake_send_expired_claim_denied"
            )
    if sender.wait(timeout=5) != 0 or len(checks) != 3 or not resources.remove("mail"):
        raise RuntimeError("native_mail_sender_exit_unconfirmed")
    exclusive(True)
    checks.append("web_EX_only_after_actual_sender_exit_and_container_absence")
    return {
        "status": "passed",
        "checks": checks,
        "device": locked["device"],
        "inode": locked["inode"],
        "production_provider_calls": 0,
    }
