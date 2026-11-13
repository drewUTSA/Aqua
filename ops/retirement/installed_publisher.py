"""Bounded installed publisher with an explicit reviewed image/code profile pin."""

import argparse
from contextlib import contextmanager
import json
import re
import signal
import threading

if __package__:
    from .operator_files import PRIVATE, pinned
    from .publisher_launcher import Unavailable, launch
else:
    from operator_files import PRIVATE, pinned
    from publisher_launcher import Unavailable, launch


def _execute(expected: str, check_cancelled, *, scope=None) -> str:
    if not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise RuntimeError("retirement_publisher_profile_pin_required")
    root = PRIVATE
    if scope is not None:
        if __package__:
            from .publisher_launcher import scoped
        else:
            from publisher_launcher import scoped
        root, _, _, _ = scoped(scope)
    value = pinned(root / "host/publisher.json", expected)
    if (
        set(value)
        != {
            "schemaVersion",
            "runtime_image",
            "source_sha256",
            "code_manifest_sha256",
            "host_code_manifest_sha256",
        }
        or type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or any(
            type(value[key]) is not str or not re.fullmatch(r"[a-f0-9]{64}", value[key])
            for key in (
                "source_sha256",
                "code_manifest_sha256",
                "host_code_manifest_sha256",
            )
        )
        or type(value["runtime_image"]) is not str
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", value["runtime_image"])
    ):
        raise RuntimeError("retirement_publisher_profile_invalid")
    if __package__:
        from .install import sources
    else:
        from install import sources
    sources(value["host_code_manifest_sha256"])
    check_cancelled()
    if scope is None:
        return launch(
            PRIVATE, value["code_manifest_sha256"], image=value["runtime_image"]
        )
    return launch(
        root, value["code_manifest_sha256"], image=value["runtime_image"], scope=scope
    )


_active = False


@contextmanager
def _deferred_cancellation():
    """Defer interruption through bounded work/cleanup; restore caller handlers."""
    global _active
    if _active or threading.current_thread() is not threading.main_thread():
        raise Unavailable()
    previous = {}
    cancelled = False

    def cancel(number, frame):
        nonlocal cancelled
        # Never raise inside the launcher's finally, including its first signal.
        cancelled = True

    def check_cancelled():
        if cancelled:
            raise Unavailable() from None

    try:
        _active = True
        try:
            for number in (signal.SIGTERM, signal.SIGINT):
                previous[number] = signal.getsignal(number)
                signal.signal(number, cancel)
        except BaseException:
            raise Unavailable() from None
        yield check_cancelled
    finally:
        try:
            for number, handler in previous.items():
                signal.signal(number, handler)
        finally:
            _active = False


def _checked_execute(expected, check_cancelled, *, scope=None):
    check_cancelled()
    try:
        if scope is None:
            status = _execute(expected, check_cancelled)
        else:
            status = _execute(expected, check_cancelled, scope=scope)
    except BaseException:
        check_cancelled()
        raise
    check_cancelled()
    return status


def execute(expected: str, *, scope=None) -> str:
    with _deferred_cancellation() as check_cancelled:
        if scope is None:
            return _checked_execute(expected, check_cancelled)
        return _checked_execute(expected, check_cancelled, scope=scope)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--profile-sha256", default="")
    args = parser.parse_args()
    if not args.execute:
        print(
            json.dumps(
                {"status": "prepared_only", "private_reads": 0, "Docker_actions": 0}
            )
        )
        return
    failed = False
    try:
        with _deferred_cancellation() as check_cancelled:
            try:
                status = _checked_execute(args.profile_sha256, check_cancelled)
            except BaseException:
                failed, status = True, "unavailable"
            print(json.dumps({"status": status}))
    except BaseException:
        failed = True
        print(json.dumps({"status": "unavailable"}))
    if failed:
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
