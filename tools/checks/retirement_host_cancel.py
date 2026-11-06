"""Controlled cancellation for an owned native fixture, including its cleanup."""

import signal


class Cancelled(RuntimeError):
    pass


class Cancellation:
    def __init__(self):
        self.cleaning = False
        self.previous = {}

    def __enter__(self):
        for value in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            self.previous[value] = signal.getsignal(value)
            signal.signal(value, self.receive)
        return self

    def receive(self, signum, frame):
        if not self.cleaning:
            raise Cancelled("native_fixture_cancelled")

    def __exit__(self, kind, value, traceback):
        for number, handler in self.previous.items():
            signal.signal(number, handler)
