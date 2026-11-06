"""Real Python child, real runtime signals, actual launcher finally, modeled I/O."""

import argparse
import builtins
from contextlib import contextmanager, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import signal
import stat
import sys
import time
import threading
import traceback
from types import ModuleType, SimpleNamespace


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--case", required=True)
    args = parser.parse_args()
    full_case = args.case
    direct = full_case.startswith("direct_")
    case = full_case[len("direct_") :] if direct else full_case
    external = case.startswith("external_")
    case = case[len("external_") :] if external else case
    events = {
        "private_reads": 0,
        "source_checks": 0,
        "docker_model_calls": 0,
        "cleanup_entered": False,
        "cleanup_completed": False,
        "cleanup_uncertain": False,
        "singleton_exited": False,
        "signal_registrations": 0,
        "signal_deliveries": 0,
        "removed_exact_id": False,
        "ownership_metadata_checked": False,
        "create_returned_identifier": False,
    }
    prior = {
        number: signal.getsignal(number) for number in (signal.SIGTERM, signal.SIGINT)
    }
    output = io.StringIO()
    profile = {
        "schemaVersion": 1,
        "runtime_image": "sha256:" + "5" * 64,
        "source_sha256": "2" * 64,
        "code_manifest_sha256": "4" * 64,
        "host_code_manifest_sha256": "3" * 64,
    }
    real_print = builtins.print

    class ModelPath:
        def __init__(self, name):
            self.name = name

        @property
        def parent(self):
            return ModelPath(self.name.rsplit("/", 1)[0])

        def __truediv__(self, name):
            return ModelPath(self.name + "/" + name)

        def __str__(self):
            return self.name

        def stat(self):
            assert self.name == "/usr/bin/docker"
            return SimpleNamespace(st_mode=stat.S_IFREG | 0o755, st_uid=0)

        def lstat(self):
            assert self.name == "/var/run/docker.sock"
            return SimpleNamespace(st_mode=stat.S_IFSOCK | 0o600, st_uid=0)

    def raise_at(phase, number):
        observed = events["signal_deliveries"]
        real_print(
            json.dumps({"event": "signal_point", "phase": phase, "signal": number}),
            file=sys.__stdout__,
            flush=True,
        )
        if external:
            # Parent uses os.kill only when the parent is actually POSIX.
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if events["signal_deliveries"] > observed:
                    return
                time.sleep(0.01)
            raise RuntimeError("public_model_external_signal_missing")
        signal.raise_signal(number)

    @contextmanager
    def singleton(root):
        try:
            yield case != "busy"
        finally:
            events["singleton_exited"] = True

    load("operator_scope", Path(__file__).with_name("operator_scope.py"))
    launcher = load("publisher_launcher", args.launcher)

    class ModelDocker(launcher.Docker):
        # Keep actual __init__, ids, owned and clean; model only the Docker RPC.
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.present = False
            self.labels = {}
            self.cleanup_signal_sent = False
            events["work_budget_seconds"] = self.work_deadline - self.started
            events["total_budget_seconds"] = self.deadline - self.started

        def call(self, *arguments, cleanup=False, **kwargs):
            events["docker_model_calls"] += 1
            if cleanup:
                events["cleanup_entered"] = True
                first_here = (
                    case.startswith("normal_cleanup_")
                    and arguments[:2] == ("container", "ls")
                    or case.startswith("normal_rm_")
                    and arguments[:2] == ("container", "rm")
                )
                if first_here and not self.cleanup_signal_sent:
                    self.cleanup_signal_sent = True
                    raise_at(
                        (
                            "cleanup_owned_active"
                            if arguments[:2] == ("container", "ls")
                            else "cleanup_rm_active"
                        ),
                        signal.SIGTERM if case.endswith("TERM") else signal.SIGINT,
                    )
                elif "repeat" in case and self.cleanup_signal_sent:
                    signal.raise_signal(
                        signal.SIGINT if case.endswith("TERM") else signal.SIGTERM
                    )
                elif case in {"repeat_TERM", "repeat_INT"}:
                    signal.raise_signal(
                        signal.SIGINT if case.endswith("TERM") else signal.SIGTERM
                    )
            if arguments[:2] == ("container", "ls"):
                if cleanup and "id=" + "a" * 64 in arguments:
                    events["cleanup_completed"] = not self.present
                    events["cleanup_uncertain"] = self.present
                return "a" * 64 if self.present else ""
            if arguments[:2] == ("container", "inspect"):
                assert arguments[-1] == "a" * 64
                events["ownership_metadata_checked"] = True
                return (
                    "a" * 64
                    + "\n/aqua-retirement-publisher\n"
                    + json.dumps(self.labels)
                )
            if arguments[:2] == ("image", "inspect"):
                return profile["runtime_image"]
            if arguments[:2] == ("volume", "inspect"):
                return "aqua_app_sockets"
            if arguments[:2] == ("container", "create"):
                self.present = True
                self.labels = dict(
                    arguments[index + 1].split("=", 1)
                    for index, item in enumerate(arguments)
                    if item == "--label"
                )
                if case.startswith("create_"):
                    raise_at(
                        "create_response_pending",
                        signal.SIGTERM if case.endswith("TERM") else signal.SIGINT,
                    )
                    if case.startswith("create_failure_"):
                        raise RuntimeError("PUBLIC_MODEL_PRIVATE_SENTINEL")
                events["create_returned_identifier"] = True
                return "a" * 64
            if arguments[:2] == ("container", "rm"):
                assert cleanup and arguments == ("container", "rm", "--force", "a" * 64)
                assert self.labels["io.aqua.purpose"] == "retirement-publisher"
                if case == "cleanup_false":
                    raise launcher.Unavailable()
                self.present = False
                events["removed_exact_id"] = True
                return ""
            assert arguments[:2] == ("container", "start")
            if case in {
                "start_TERM",
                "start_INT",
                "repeat_TERM",
                "repeat_INT",
                "external_TERM",
                "external_INT",
            }:
                raise_at(
                    "start_identifier_known",
                    signal.SIGTERM if case.endswith("TERM") else signal.SIGINT,
                )
            return json.dumps(
                {"status": "checked" if case == "checked" else "idle", "steps": 0}
            )

    launcher.directory = lambda path: None
    launcher.code_ready = lambda root, expected: None
    launcher.singleton = singleton
    launcher.append_flag = lambda path: None
    launcher.file_fd = lambda *args, **kwargs: 77
    launcher.os = SimpleNamespace(
        name="posix", geteuid=lambda: 1000, close=lambda fd: None
    )
    launcher.Path = ModelPath
    launcher.Docker = ModelDocker

    operator_files = ModuleType("operator_files")
    operator_files.PRIVATE = launcher.PRIVATE

    def pinned(path, expected):
        events["private_reads"] += 1
        assert expected == "1" * 64
        if case in {"before_launch_TERM", "before_launch_INT"}:
            signal.raise_signal(
                signal.SIGTERM if case.endswith("TERM") else signal.SIGINT
            )
        if case == "reentrant":
            return installed.execute("1" * 64)
        if case in {"error_RuntimeError", "print_signal"}:
            raise RuntimeError("PUBLIC_MODEL_PRIVATE_SENTINEL")
        if case == "error_KeyboardInterrupt":
            raise KeyboardInterrupt("PUBLIC_MODEL_PRIVATE_SENTINEL")
        if case == "error_SystemExit":
            raise SystemExit("PUBLIC_MODEL_PRIVATE_SENTINEL")
        return dict(profile)

    operator_files.pinned = pinned
    sys.modules["operator_files"] = operator_files
    installer = ModuleType("install")

    def sources(expected):
        assert expected == "3" * 64
        events["source_checks"] += 1

    installer.sources = sources
    sys.modules["install"] = installer
    installed = load("installed_publisher", args.source)

    def register(number, handler):
        events["signal_registrations"] += 1
        if case == "registration_failure" and events["signal_registrations"] == 2:
            raise ValueError("PUBLIC_MODEL_PRIVATE_SENTINEL")
        if handler is prior[number]:
            return signal.signal(number, handler)

        def counted(number, frame):
            events["signal_deliveries"] += 1
            return handler(number, frame)

        return signal.signal(number, counted)

    installed.signal = SimpleNamespace(
        SIGTERM=signal.SIGTERM,
        SIGINT=signal.SIGINT,
        getsignal=signal.getsignal,
        signal=register,
    )

    def print_with_signal(*values, **kwargs):
        if case == "print_signal":
            signal.raise_signal(signal.SIGTERM)
        return real_print(*values, **kwargs)

    installed.print = print_with_signal
    sys.argv = [str(args.source)]
    if case != "prepared":
        sys.argv += [
            "--execute",
            "--profile-sha256",
            "bad" if case == "invalid_pin" else "1" * 64,
        ]
    code, escaped, returned, fixed_unavailable = 0, None, None, False
    try:
        with redirect_stdout(output):
            if direct:
                if case == "nonmain_thread":
                    observed = {}

                    def worker():
                        try:
                            observed["returned"] = installed.execute("1" * 64)
                        except BaseException as error:
                            observed["error"] = error

                    thread = threading.Thread(target=worker)
                    thread.start()
                    thread.join(timeout=2)
                    assert not thread.is_alive(), "public_model_thread_deadline"
                    if "error" in observed:
                        raise observed["error"]
                    returned = observed["returned"]
                else:
                    returned = installed.execute("1" * 64)
            else:
                installed.main()
    except BaseException as error:
        escaped = type(error).__name__
        fixed_unavailable = (
            type(error) is launcher.Unavailable
            and str(error) == "retirement_publisher_launcher_unavailable"
        )
        events["exception_trace_sentinel_exposed"] = (
            "PUBLIC_MODEL_PRIVATE_SENTINEL"
            in "".join(traceback.format_exception(error))
        )
        code = (
            error.code
            if isinstance(error, SystemExit) and type(error.code) is int
            else 1
        )
    events["handlers_restored"] = all(
        signal.getsignal(number) == handler for number, handler in prior.items()
    )
    events["active_guard_released"] = getattr(installed, "_active", False) is False
    raw = output.getvalue()
    events.update(
        case=full_case,
        invocation="direct_execute" if direct else "CLI",
        returned_status=returned,
        fixed_unavailable=fixed_unavailable,
        mode="real_child_signals_actual_launch_and_Docker_clean_only_RPC_and_private_IO_modeled",
        exit_code=code,
        escaped_type=escaped,
        entrypoint_output=raw,
        sentinel_exposed="PUBLIC_MODEL_PRIVATE_SENTINEL" in raw,
    )
    real_print(json.dumps(events, sort_keys=True), flush=True)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
