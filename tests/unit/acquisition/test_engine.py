import queue
import threading

import pytest
from structlog.testing import capture_logs

from dms.acquisition.engine import Engine
from dms.domain.events import ClosedEvent, StartedEvent
from dms.domain.records import MeterRecord, WriterRecord
from dms.logs import events
from dms.messages import EngineMessage, MeterReading, SignalStates, TankSignals, Tick
from tests.unit.domain.builders import SECOND_NS, build_silo


def build() -> tuple[Engine, queue.Queue[EngineMessage], queue.Queue[WriterRecord]]:
    in_queue: queue.Queue[EngineMessage] = queue.Queue()
    out_queue: queue.Queue[WriterRecord] = queue.Queue()
    engine = Engine(
        in_queue=in_queue,
        out_queue=out_queue,
        silos_by_meter={
            "m1": build_silo(1, tank_ids=(1,)),
            "m2": build_silo(2, tank_ids=(2,)),
        },
        stop_event=threading.Event(),
    )
    return engine, in_queue, out_queue


def records(out_queue: queue.Queue[WriterRecord]) -> list[WriterRecord]:
    items: list[WriterRecord] = []
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
        silos_by_meter={"m1": build_silo(1)},
        stop_event=stop_event,
    )
    in_queue.put(MeterReading("m1", 1, 0, 0))
    stop_event.set()

    engine.run()

    assert in_queue.empty()


def test_stale_and_recovered_reading_are_logged_once_each() -> None:
    engine, in_queue, _ = build()
    in_queue.put(MeterReading("m1", 100, 0, 10 * SECOND_NS))
    for tick_s in (12, 13, 14):
        in_queue.put(Tick(0, tick_s * SECOND_NS))
    in_queue.put(MeterReading("m1", 110, 0, 15 * SECOND_NS))
    in_queue.put(Tick(0, 15 * SECOND_NS))

    with capture_logs() as logs:
        for _ in range(6):
            engine.step()

    reading_logs = [entry for entry in logs if entry["event"].startswith("silo.reading_")]
    assert [(entry["event"], entry["silo_id"]) for entry in reading_logs] == [
        (events.SILO_READING_STALE, 1),
        (events.SILO_READING_STALE_ENDED, 1),
    ]
    assert reading_logs[1]["duration_s"] == 4.0


def test_signal_changes_are_logged_for_the_right_tanks() -> None:
    engine, in_queue, _ = build()
    in_queue.put(
        SignalStates(
            (
                TankSignals(1, dispense=True, refill=False),
                TankSignals(2, dispense=False, refill=False),
            ),
            0,
            0,
        )
    )

    with capture_logs() as logs:
        engine.step()

    assert [
        (entry["event"], entry["tank_id"], entry["signal"], entry["active"], entry["previous"])
        for entry in logs
        if entry["event"] == events.SIGNAL_CHANGED
    ] == [
        (events.SIGNAL_CHANGED, 1, "dispense", True, None),
        (events.SIGNAL_CHANGED, 1, "refill", False, None),
        (events.SIGNAL_CHANGED, 2, "dispense", False, None),
        (events.SIGNAL_CHANGED, 2, "refill", False, None),
    ]


def test_unchanged_signals_are_not_logged_again() -> None:
    engine, in_queue, _ = build()
    states = SignalStates((TankSignals(1, dispense=True, refill=False),), 0, 0)
    in_queue.put(states)
    in_queue.put(states)
    engine.step()

    with capture_logs() as logs:
        engine.step()

    assert logs == []


def signals_message(mono_s: float, *, dispense: bool) -> SignalStates:
    mono_ns = round(mono_s * SECOND_NS)
    return SignalStates((TankSignals(1, dispense=dispense, refill=False),), mono_ns, mono_ns)


def run_dispense(
    engine: Engine, in_queue: queue.Queue[EngineMessage], *, end_value_kg: int | None
) -> None:
    in_queue.put(MeterReading("m1", 500, 0, 9 * SECOND_NS))
    in_queue.put(signals_message(9.5, dispense=False))
    in_queue.put(signals_message(10.0, dispense=True))
    if end_value_kg is not None:
        in_queue.put(MeterReading("m1", end_value_kg, 0, 14 * SECOND_NS))
    in_queue.put(signals_message(14.5, dispense=False))
    for _ in range(5 if end_value_kg is not None else 4):
        engine.step()


def test_started_and_closed_events_go_to_the_writer_queue() -> None:
    engine, in_queue, out_queue = build()

    run_dispense(engine, in_queue, end_value_kg=380)

    started, closed = [item for item in records(out_queue) if not isinstance(item, MeterRecord)]
    assert isinstance(started, StartedEvent)
    assert isinstance(closed, ClosedEvent)
    assert started.event_id == closed.event_id
    assert (started.start_value_kg, closed.end_value_kg) == (500, 380)


def test_started_and_completed_events_are_logged_with_the_delta() -> None:
    engine, in_queue, _ = build()

    with capture_logs() as logs:
        run_dispense(engine, in_queue, end_value_kg=380)

    event_logs = [entry for entry in logs if entry["event"].startswith("event.")]
    assert [entry["event"] for entry in event_logs] == [
        events.EVENT_STARTED,
        events.EVENT_COMPLETED,
    ]
    assert event_logs[0]["event_id"] == event_logs[1]["event_id"]
    assert event_logs[0]["event_id"] == "00000000-0000-0000-0000-000000000001"
    assert (event_logs[1]["delta_kg"], event_logs[1]["duration_s"]) == (-120, 4.5)
    assert (event_logs[1]["tank_id"], event_logs[1]["type"]) == (1, "dispense")


def test_incomplete_event_is_logged_as_an_error_with_both_qualities() -> None:
    engine, in_queue, _ = build()

    with capture_logs() as logs:
        run_dispense(engine, in_queue, end_value_kg=None)

    (incomplete,) = [entry for entry in logs if entry["event"] == events.EVENT_INCOMPLETE]
    assert incomplete["log_level"] == "error"
    assert (incomplete["start_quality"], incomplete["end_quality"]) == ("fresh", "stale_reading")
    assert incomplete["end_value_kg"] is None


def test_orphaned_event_is_logged_as_a_warning() -> None:
    engine, in_queue, out_queue = build()
    in_queue.put(signals_message(1.0, dispense=True))

    with capture_logs() as logs:
        engine.step()

    (orphaned,) = [entry for entry in logs if entry["event"] == events.EVENT_ORPHANED]
    assert orphaned["log_level"] == "warning"
    assert [type(item) for item in records(out_queue)] == [StartedEvent]


def test_lost_signals_log_the_state_before_the_closed_event_and_its_end() -> None:
    engine, in_queue, out_queue = build()
    in_queue.put(MeterReading("m1", 500, 0, 9 * SECOND_NS))
    in_queue.put(signals_message(9.5, dispense=False))
    in_queue.put(signals_message(10.0, dispense=True))
    in_queue.put(Tick(0, 12 * SECOND_NS))
    in_queue.put(signals_message(15.0, dispense=False))

    with capture_logs() as logs:
        for _ in range(5):
            engine.step()

    names = [
        entry["event"]
        for entry in logs
        if entry["event"].startswith(("event.", "silo.signals")) and entry.get("silo_id", 1) == 1
    ]
    assert names[:4] == [
        events.EVENT_STARTED,
        events.SILO_SIGNALS_STALE,
        events.EVENT_INCOMPLETE,
        events.SILO_SIGNALS_STALE_ENDED,
    ]
    (incomplete,) = [entry for entry in logs if entry["event"] == events.EVENT_INCOMPLETE]
    assert (incomplete["start_quality"], incomplete["end_quality"]) == ("fresh", "signal_lost")
    ended = [entry for entry in logs if entry["event"] == events.SILO_SIGNALS_STALE_ENDED]
    assert ended[0]["duration_s"] == 4.0
    closed = [item for item in records(out_queue) if isinstance(item, ClosedEvent)]
    assert [item.end_quality for item in closed] == ["signal_lost"]


def test_handle_processes_a_message_without_the_queue() -> None:
    engine, _, out_queue = build()

    engine.handle(MeterReading("m1", 100, 5, SECOND_NS))
    engine.handle(Tick(0, SECOND_NS + 1))

    assert records(out_queue) == [MeterRecord(1, 5, 100)]


def build_stopping_engine() -> tuple[
    Engine, queue.Queue[EngineMessage], queue.Queue[WriterRecord], threading.Event
]:
    in_queue: queue.Queue[EngineMessage] = queue.Queue()
    out_queue: queue.Queue[WriterRecord] = queue.Queue()
    stop_event = threading.Event()
    engine = Engine(
        in_queue=in_queue,
        out_queue=out_queue,
        silos_by_meter={"m1": build_silo(1, tank_ids=(1,))},
        stop_event=stop_event,
    )
    return engine, in_queue, out_queue, stop_event


def test_stop_closes_open_events_after_handling_the_queued_messages() -> None:
    engine, in_queue, out_queue, stop_event = build_stopping_engine()
    in_queue.put(MeterReading("m1", 500, 0, 9 * SECOND_NS))
    in_queue.put(signals_message(9.5, dispense=False))
    in_queue.put(signals_message(10.0, dispense=True))
    in_queue.put(signals_message(10.5, dispense=True))
    stop_event.set()

    with capture_logs() as logs:
        engine.run()

    started, closed = [item for item in records(out_queue) if not isinstance(item, MeterRecord)]
    assert isinstance(started, StartedEvent)
    assert isinstance(closed, ClosedEvent)
    assert (closed.end_quality, closed.end_wall_ns, closed.duration_ns) == (
        "service_stopped",
        round(10.5 * SECOND_NS),
        round(0.5 * SECOND_NS),
    )
    (incomplete,) = [entry for entry in logs if entry["event"] == events.EVENT_INCOMPLETE]
    assert incomplete["log_level"] == "error"
    assert (incomplete["start_quality"], incomplete["end_quality"]) == ("fresh", "service_stopped")


def test_stop_without_open_events_writes_nothing() -> None:
    engine, in_queue, out_queue, stop_event = build_stopping_engine()
    in_queue.put(signals_message(9.5, dispense=False))
    stop_event.set()

    engine.run()

    assert records(out_queue) == []


def test_crash_of_the_engine_closes_no_open_events(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, in_queue, out_queue, _ = build_stopping_engine()
    in_queue.put(MeterReading("m1", 500, 0, 9 * SECOND_NS))
    in_queue.put(signals_message(9.5, dispense=False))
    in_queue.put(signals_message(10.0, dispense=True))
    in_queue.put(Tick(0, 11 * SECOND_NS))
    handle = engine.handle
    handled: list[EngineMessage] = []

    def handle_until_crash(message: EngineMessage) -> None:
        if isinstance(message, Tick):
            raise RuntimeError("engine crashed")
        handled.append(message)
        handle(message)

    monkeypatch.setattr(engine, "handle", handle_until_crash)

    with pytest.raises(RuntimeError, match="engine crashed"):
        engine.run()

    assert len(handled) == 3
    assert [item for item in records(out_queue) if isinstance(item, ClosedEvent)] == []
