import queue
import threading

from dms.acquisition.engine import Engine
from dms.domain.records import MeterRecord
from dms.domain.silo import Silo
from dms.messages import EngineMessage, MeterReading, Tick

SECOND_NS = 1_000_000_000


def build() -> tuple[Engine, queue.Queue[EngineMessage], queue.Queue[MeterRecord]]:
    in_queue: queue.Queue[EngineMessage] = queue.Queue()
    out_queue: queue.Queue[MeterRecord] = queue.Queue()
    engine = Engine(
        in_queue=in_queue,
        out_queue=out_queue,
        silos_by_meter={"m1": Silo(1, SECOND_NS), "m2": Silo(2, SECOND_NS)},
        stop_event=threading.Event(),
    )
    return engine, in_queue, out_queue


def records(out_queue: queue.Queue[MeterRecord]) -> list[MeterRecord]:
    items: list[MeterRecord] = []
    while not out_queue.empty():
        items.append(out_queue.get_nowait())
    return items


def test_reading_is_routed_to_its_silo_and_tick_emits_records() -> None:
    engine, in_queue, out_queue = build()
    in_queue.put(MeterReading("m1", 100, 5, 1 * SECOND_NS))
    in_queue.put(MeterReading("m2", 200, 6, 1 * SECOND_NS))
    in_queue.put(Tick(0, SECOND_NS + 1))

    for _ in range(3):
        engine.step()

    assert records(out_queue) == [MeterRecord(1, 5, 100), MeterRecord(2, 6, 200)]


def test_tick_without_readings_emits_nothing() -> None:
    engine, in_queue, out_queue = build()
    in_queue.put(Tick(0, SECOND_NS))

    engine.step()

    assert records(out_queue) == []


def test_reading_from_unknown_meter_is_ignored() -> None:
    engine, in_queue, out_queue = build()
    in_queue.put(MeterReading("m9", 1, 0, SECOND_NS))
    in_queue.put(Tick(0, SECOND_NS))

    engine.step()
    engine.step()

    assert records(out_queue) == []


def test_run_drains_the_queue_after_stop() -> None:
    engine, in_queue, out_queue = build()
    stop_event = threading.Event()
    engine = Engine(
        in_queue=in_queue,
        out_queue=out_queue,
        silos_by_meter={"m1": Silo(1, SECOND_NS)},
        stop_event=stop_event,
    )
    in_queue.put(MeterReading("m1", 1, 0, 0))
    stop_event.set()

    engine.run()

    assert in_queue.empty()
