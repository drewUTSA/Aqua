"""Opt-in inherited deadline; no transport, signals, keys or activation."""

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field


class BudgetDenied(ValueError):
    """Only fixed diagnostics leave this helper."""


def finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


# Cleanup belongs inside the inherited end. These reserves reflect the existing
# pipeline finally blocks, not a new allowance after the parent deadline.
# Native SQL already includes its remote 30-second cleanup inside its seconds;
# only the existing three-second local process.wait is reserved here.
OPERATIONS = {
    "head": (20.0, 4.0, 0.0),
    "encrypt": (120.0, 8.0, 0.0),
    "decrypt": (120.0, 4.0, 0.0),
    "sql_restore": (120.0, 3.0, 45.0),
}


@dataclass(frozen=True)
class Deadline:
    """All timestamps MUST originate from the same caller's monotonic clock.

    Capture install_started before requesting installation, not when its wait
    message arrives. A server monotonic or UTC timestamp cannot be substituted
    for a local monotonic timestamp. This does not preempt running work.
    """

    install_started: float
    owner_end: float
    client_end: float
    run_end: float
    clock: Callable[[], float] = field(
        default=time.monotonic, repr=False, compare=False
    )
    end: float = field(init=False)
    _last: float = field(init=False, repr=False, compare=False)
    _poisoned: bool = field(init=False, default=False, repr=False, compare=False)

    def __post_init__(self):
        values = (self.install_started, self.owner_end, self.client_end, self.run_end)
        if not all(finite(value) for value in values) or not callable(self.clock):
            raise BudgetDenied("authority_session_clock_invalid")
        now = self.clock()
        end = min(
            self.install_started + 180.0, self.owner_end, self.client_end, self.run_end
        )
        if not finite(now) or not self.install_started <= now < end:
            raise BudgetDenied("authority_session_expired_or_clock_invalid")
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "_last", now)

    def _now(self):
        if self._poisoned:
            raise BudgetDenied("authority_session_clock_invalid")
        now = self.clock()
        if not finite(now):
            object.__setattr__(self, "_poisoned", True)
            raise BudgetDenied("authority_session_clock_invalid")
        if now < self._last:
            object.__setattr__(self, "_poisoned", True)
            raise BudgetDenied("authority_session_clock_rollback")
        object.__setattr__(self, "_last", now)
        return now

    def checkpoint(self):
        """A late result must be denied even if an external alarm was reset."""
        if self._now() >= self.end:
            raise BudgetDenied("authority_session_expired")

    def seconds(self, operation, requested=None):
        """Return a cap to pass directly to the original primitive/adapter.

        Recompute immediately before the actual primitive. Do not cache a cap
        across archive verification, encryption, readback or another callback.
        The native adapter itself must remain the exact original type.
        """
        if type(operation) is not str or operation not in OPERATIONS:
            raise BudgetDenied("authority_session_operation_invalid")
        cap, reserve, minimum = OPERATIONS[operation]
        if requested is None:
            requested = cap
        if not finite(requested) or not 0 < requested <= cap:
            raise BudgetDenied("authority_session_operation_budget_invalid")
        available = min(float(requested), self.end - self._now() - reserve)
        if available <= minimum:
            raise BudgetDenied("authority_session_insufficient_budget")
        return available


def checked(deadline):
    """Reject duck-typed/subclass budgets before trusted client operations."""
    if deadline is not None:
        if type(deadline) is not Deadline:
            raise BudgetDenied("authority_session_deadline_required")
        deadline.checkpoint()
