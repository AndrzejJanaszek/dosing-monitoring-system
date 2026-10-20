import queue
import threading

from dms.acquisition.ticker import TickTimer
from dms.messages import EngineMessage, Tick
from dms.units import NS_PER_S
from tests.fakes import ManualClock


def build(
    clock: ManualClock, stop_event: threading.Event | None = None
) -> tuple[TickTimer, queue.Queue[EngineMessage]]:
    out_queue: queue.Queue[EngineMessage] = queue.Queue()
    timer = TickTimer(
        clock=clock,
        interval_ns=NS_PER_S,
        out_queue=out_queue,
        stop_event=stop_event if stop_event is not None else threading.Event(),
        wait=clock.waiter(),
    )
    return timer, out_queue


def ticks(out_queue: queue.Queue[EngineMessage]) -> list[Tick]:
    items: list[Tick] = []
    while not out_queue.empty():
        message = out_queue.get_nowait()
        assert isinstance(message, Tick)
        items.append(message)
    return items


def test_ticks_come_at_fixed_intervals_from_start() -> None:
    clock = ManualClock(mono_ns=5 * NS_PER_S)
    timer, out_queue = build(clock)

    for _ in range(3):
        timer.step()

    assert [tick.mono_ns for tick in ticks(out_queue)] == [
        6 * NS_PER_S,
        7 * NS_PER_S,
        8 * NS_PER_S,
    ]


def test_late_wakeup_does_not_shift_later_deadlines() -> None:
    clock = ManualClock()
    out_queue: queue.Queue[EngineMessage] = queue.Queue()
    oversleep_s = [0.3, 0.0]

    def oversleeping_wait(seconds: float) -> bool:
        clock.advance(seconds + oversleep_s.pop(0))
        return False

    timer = TickTimer(
        clock=clock,
        interval_ns=NS_PER_S,
        out_queue=out_queue,
        stop_event=threading.Event(),
        wait=oversleeping_wait,
    )

    timer.step()
    timer.step()

    assert [tick.mono_ns for tick in ticks(out_queue)] == [round(1.3 * NS_PER_S), 2 * NS_PER_S]


def test_missed_deadlines_are_skipped_not_replayed() -> None:
    clock = ManualClock()
    timer, out_queue = build(clock)
    timer.step()
    clock.advance(3.5)

    timer.step()
    timer.step()

    assert [tick.mono_ns for tick in ticks(out_queue)] == [
        NS_PER_S,
        round(4.5 * NS_PER_S),
        5 * NS_PER_S,
    ]


def test_tick_carries_both_clocks() -> None:
    clock = ManualClock(wall_ns=1_000, mono_ns=0)
    timer, out_queue = build(clock)

    timer.step()

    assert ticks(out_queue) == [Tick(1_000 + NS_PER_S, NS_PER_S)]


def test_no_tick_when_stopped_while_waiting() -> None:
    clock = ManualClock()
    out_queue: queue.Queue[EngineMessage] = queue.Queue()
    timer = TickTimer(
        clock=clock,
        interval_ns=NS_PER_S,
        out_queue=out_queue,
        stop_event=threading.Event(),
        wait=lambda _seconds: True,
    )

    timer.step()

    assert out_queue.empty()
