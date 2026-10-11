import queue
import threading
from collections.abc import Callable

from dms.acquisition.clock import Clock
from dms.messages import EngineMessage, Tick

NS_PER_S = 1_000_000_000


class TickTimer:
    def __init__(
        self,
        *,
        clock: Clock,
        interval_ns: int,
        out_queue: queue.Queue[EngineMessage],
        stop_event: threading.Event,
        wait: Callable[[float], bool] | None = None,
    ) -> None:
        self._clock = clock
        self._interval_ns = interval_ns
        self._out_queue = out_queue
        self._stop_event = stop_event
        self._wait = wait if wait is not None else stop_event.wait
        self._next_deadline_ns: int | None = None

    def run(self) -> None:
        while not self._stop_event.is_set():
            self.step()

    def step(self) -> None:
        if self._next_deadline_ns is None:
            self._next_deadline_ns = self._clock.mono_ns() + self._interval_ns
        remaining_ns = self._next_deadline_ns - self._clock.mono_ns()
        if remaining_ns > 0 and self._wait(remaining_ns / NS_PER_S):
            return
        woke_mono_ns = self._clock.mono_ns()
        self._out_queue.put(Tick(self._clock.wall_ns(), woke_mono_ns))
        self._next_deadline_ns = self._deadline_after(self._next_deadline_ns, woke_mono_ns)

    def _deadline_after(self, deadline_ns: int, now_ns: int) -> int:
        missed_intervals = max(0, (now_ns - deadline_ns) // self._interval_ns)
        return deadline_ns + (missed_intervals + 1) * self._interval_ns
