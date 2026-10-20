import time
from typing import Protocol


class Clock(Protocol):
    def wall_ns(self) -> int: ...

    def mono_ns(self) -> int: ...


class SystemClock:
    def wall_ns(self) -> int:
        return time.time_ns()

    def mono_ns(self) -> int:
        return time.monotonic_ns()
