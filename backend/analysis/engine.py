"""The supervisor may settle a job only after its engine stops owned work."""

from collections.abc import Callable
from typing import Protocol, Any

Control = Callable[[str | None], None]


class Engine(Protocol):
    def run(
        self, payload: dict[str, Any], control: Control
    ) -> tuple[dict[str, Any], int]:
        """Return after exit; Unreaped/RemoteUncertain retain physical capacity."""
        ...

    def close(self) -> None:
        """Stop owned work before the application closes its storage pool."""
        ...
