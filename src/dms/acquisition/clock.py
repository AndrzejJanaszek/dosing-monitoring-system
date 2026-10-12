import time
from typing import Protocol

NS_PER_S = 1_000_000_000


class Clock(Protocol):
    def wall_ns(self) -> int: ...

    def mono_ns(self) -> int: ...


class SystemClock:
    def wall_ns(self) -> int:
        return time.time_ns()

    def mono_ns(self) -> int:
        return time.monotonic_ns()
