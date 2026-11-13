"""Operator helpers are separate bounded processes, never request threads."""

from contextlib import contextmanager
from collections.abc import Iterator
import signal
import threading


@contextmanager
def deadline() -> Iterator[None]:
    """Fail closed rather than borrowing or extending another process deadline."""
    if threading.current_thread() is not threading.main_thread() or signal.getitimer(
        signal.ITIMER_REAL
    ) != (0.0, 0.0):
        raise RuntimeError("retirement_operator_deadline_context_invalid")
    previous = signal.getsignal(signal.SIGALRM)

    def expired(signum, frame):
        raise RuntimeError("retirement_operator_deadline")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, 120)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
