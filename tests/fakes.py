from collections.abc import Callable


class ManualClock:
    def __init__(self, wall_ns: int = 1_700_000_000_000_000_000, mono_ns: int = 0) -> None:
        self._wall_ns = wall_ns
        self._mono_ns = mono_ns

    def wall_ns(self) -> int:
        return self._wall_ns

    def mono_ns(self) -> int:
        return self._mono_ns

    def advance(self, seconds: float) -> None:
        delta = round(seconds * 1_000_000_000)
        self._wall_ns += delta
        self._mono_ns += delta

    def waiter(self) -> Callable[[float], bool]:
        def wait(seconds: float) -> bool:
            self.advance(seconds)
            return False

        return wait
