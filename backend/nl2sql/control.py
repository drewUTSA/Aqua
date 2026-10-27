"""One deadline and provider-call budget follows every pipeline stage."""

from contextvars import ContextVar
from dataclasses import dataclass, field
import time
from collections.abc import Callable


class ExecutionStopped(RuntimeError):
    pass


@dataclass
class Budget:
    deadline: float
    notify: Callable[[str], None]
    context: list[dict] = field(default_factory=list)
    context_digest: str = "standalone-question-v1"
    calls: int = 0

    def remaining(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ExecutionStopped("analysis_expired")
        return remaining

    def stage(self, name: str) -> None:
        self.remaining()
        self.notify(name)
        self.remaining()

    def provider(self, name: str = "generating") -> None:
        self.stage(name)
        if self.calls >= 4:
            raise ExecutionStopped("analysis_attempt_limit")
        self.calls += 1


CURRENT: ContextVar[Budget | None] = ContextVar("analysis_budget", default=None)


def stage(name: str) -> None:
    budget = CURRENT.get()
    if budget:
        budget.stage(name)


def remaining(default: float) -> float:
    budget = CURRENT.get()
    return min(default, budget.remaining()) if budget else default
