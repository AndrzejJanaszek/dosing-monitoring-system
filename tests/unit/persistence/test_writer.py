import queue
import threading
from collections.abc import MutableMapping, Sequence
from typing import Any
from uuid import UUID

import pytest

from dms.domain.events import ClosedEvent, EndQuality, EventKind, StartedEvent, StartQuality
from dms.domain.records import MeterRecord, WriterRecord
from dms.logs import events
from dms.persistence.record_store import DataStoreError, TransientStoreError, WriteResult
from dms.persistence.writer import Writer
from tests.fakes import ManualClock

TEST_RETRY_DELAY_S = 3.0


class FakeStore:
    def __init__(
        self,
        failures: list[Exception] | None = None,
        duplicates: int = 0,
        poison: Sequence[WriterRecord] = (),
        close_outcomes: list[bool | Exception] | None = None,
    ) -> None:
        self.failures = failures if failures is not None else []
        self.duplicates = duplicates
        self.poison = list(poison)
        self.close_outcomes = close_outcomes if close_outcomes is not None else []
        self.batches: list[list[WriterRecord]] = []
        self.closed_rejected: list[ClosedEvent] = []
        self.reconnects = 0

    def write(self, records: Sequence[WriterRecord]) -> WriteResult:
        if self.failures:
            raise self.failures.pop(0)
        if any(item in self.poison for item in records):
            raise DataStoreError("constraint violated")
        self.batches.append(list(records))
        meter_total = sum(isinstance(item, MeterRecord) for item in records)
        return WriteResult(meter_total - self.duplicates, meter_total)

    def close_rejected_event(self, event: ClosedEvent) -> bool:
        if self.failures:
            raise self.failures.pop(0)
        self.closed_rejected.append(event)
        outcome = self.close_outcomes.pop(0) if self.close_outcomes else True
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def reconnect(self) -> None:
        self.reconnects += 1


def record(index: int) -> MeterRecord:
    return MeterRecord(1, index, index)


def build(
    store: FakeStore, max_batch: int = 1000
) -> tuple[Writer, queue.Queue[WriterRecord], threading.Event]:
    in_queue: queue.Queue[WriterRecord] = queue.Queue()
    stop_event = threading.Event()
    clock = ManualClock()
    writer = Writer(
        in_queue=in_queue,
        store=store,
        stop_event=stop_event,
        max_batch=max_batch,
        retry_delay_s=TEST_RETRY_DELAY_S,
        wait=clock.waiter(),
        clock=clock,
    )
    return writer, in_queue, stop_event


def test_queued_records_are_written_as_one_batch() -> None:
    store = FakeStore()
    writer, in_queue, _ = build(store)
    for index in range(5):
        in_queue.put(record(index))

    writer.step()

    assert store.batches == [[record(index) for index in range(5)]]


def test_batch_size_is_limited() -> None:
    store = FakeStore()
    writer, in_queue, _ = build(store, max_batch=3)
    for index in range(7):
        in_queue.put(record(index))

    writer.step()
    writer.step()
    writer.step()

    assert [len(batch) for batch in store.batches] == [3, 3, 1]


def test_step_on_empty_queue_writes_nothing() -> None:
    store = FakeStore()
    writer, _, _ = build(store)

    writer.step()

    assert store.batches == []


def test_transient_error_reconnects_and_retries_same_batch(
    logs: list[MutableMapping[str, Any]],
) -> None:
    store = FakeStore([TransientStoreError("down"), TransientStoreError("still down")])
    writer, in_queue, _ = build(store)
    in_queue.put(record(1))

    writer.step()

    assert store.batches == [[record(1)]]
    assert store.reconnects == 2
    assert [entry["event"] for entry in logs] == [events.DB_WRITE_ERROR, events.DB_WRITE_RECOVERED]
    assert logs[1]["outage_s"] == 2 * TEST_RETRY_DELAY_S


def test_other_error_is_fatal_and_logged(logs: list[MutableMapping[str, Any]]) -> None:
    store = FakeStore([RuntimeError("disk full")])
    writer, in_queue, stop_event = build(store)
    in_queue.put(record(1))

    with pytest.raises(RuntimeError, match="disk full"):
        writer.run()

    assert [entry["event"] for entry in logs] == [events.WRITER_FATAL]
    assert not stop_event.is_set()


def test_run_flushes_everything_after_stop() -> None:
    store = FakeStore()
    writer, in_queue, stop_event = build(store, max_batch=2)
    for index in range(5):
        in_queue.put(record(index))
    stop_event.set()

    writer.run()

    assert [len(batch) for batch in store.batches] == [2, 2, 1]
    assert in_queue.empty()


def test_run_flushes_everything_and_reports_flushed() -> None:
    store = FakeStore()
    writer, in_queue, stop_event = build(store)
    in_queue.put(record(1))
    stop_event.set()

    writer.run()

    assert writer.flushed


def test_outage_during_stop_abandons_batch_and_queue(
    logs: list[MutableMapping[str, Any]],
) -> None:
    store = FakeStore([TransientStoreError("down")] * 10)
    writer, in_queue, stop_event = build(store, max_batch=2)
    for index in range(5):
        in_queue.put(record(index))
    stop_event.set()

    writer.run()

    assert not writer.flushed
    assert in_queue.empty()
    assert store.batches == []
    assert [entry["event"] for entry in logs] == [events.DB_WRITE_ERROR, events.WRITER_ABANDONED]
    assert logs[-1]["lost_records"] == 5


def test_stop_during_outage_ends_retrying_after_one_more_attempt() -> None:
    store = FakeStore([TransientStoreError("down")] * 10)
    in_queue: queue.Queue[WriterRecord] = queue.Queue()
    stop_event = threading.Event()
    waits: list[float] = []

    def wait(seconds: float) -> bool:
        waits.append(seconds)
        stop_event.set()
        return True

    writer = Writer(in_queue=in_queue, store=store, stop_event=stop_event, wait=wait)
    in_queue.put(record(1))

    writer.run()

    assert len(waits) == 1
    assert store.reconnects == 1
    assert not writer.flushed


def test_skipped_duplicates_are_logged(logs: list[MutableMapping[str, Any]]) -> None:
    store = FakeStore(duplicates=2)
    writer, in_queue, _ = build(store)
    for index in range(5):
        in_queue.put(record(index))

    writer.step()

    assert [entry["event"] for entry in logs] == [events.DB_READINGS_SKIPPED]
    assert (logs[0]["skipped"], logs[0]["batch_size"]) == (2, 5)


def started_event() -> StartedEvent:
    return StartedEvent(
        event_id=UUID(int=1),
        tank_id=1,
        kind=EventKind.DISPENSE,
        start_wall_ns=10,
        start_value_kg=500,
        start_quality=StartQuality.FRESH,
    )


def closed_event() -> ClosedEvent:
    return ClosedEvent(
        event_id=UUID(int=1),
        tank_id=1,
        kind=EventKind.DISPENSE,
        start_wall_ns=10,
        start_value_kg=500,
        end_wall_ns=20,
        end_value_kg=400,
        duration_ns=10,
        start_quality=StartQuality.FRESH,
        end_quality=EndQuality.FRESH,
    )


def test_mixed_records_are_written_as_one_batch() -> None:
    store = FakeStore()
    writer, in_queue, _ = build(store)
    mixed: list[WriterRecord] = [record(1), started_event(), record(2), closed_event()]
    for item in mixed:
        in_queue.put(item)

    writer.step()

    assert store.batches == [mixed]


def test_skipped_readings_are_counted_without_events(
    logs: list[MutableMapping[str, Any]],
) -> None:
    store = FakeStore(duplicates=1)
    writer, in_queue, _ = build(store)
    for item in (record(1), record(2), started_event(), closed_event()):
        in_queue.put(item)

    writer.step()

    assert [entry["event"] for entry in logs] == [events.DB_READINGS_SKIPPED]
    assert (logs[0]["skipped"], logs[0]["batch_size"]) == (1, 2)


def test_batch_of_only_events_logs_no_skipped_readings(
    logs: list[MutableMapping[str, Any]],
) -> None:
    store = FakeStore()
    writer, in_queue, _ = build(store)
    in_queue.put(started_event())
    in_queue.put(closed_event())

    writer.step()

    assert logs == []


def test_record_rejected_by_the_database_is_skipped_and_the_rest_of_the_batch_is_written(
    logs: list[MutableMapping[str, Any]],
) -> None:
    store = FakeStore(poison=[record(2)])
    writer, in_queue, _ = build(store)
    for index in range(4):
        in_queue.put(record(index))

    writer.step()

    assert store.batches == [[record(0)], [record(1)], [record(3)]]
    (rejected,) = logs
    assert rejected["event"] == events.DB_RECORD_REJECTED
    assert rejected["log_level"] == "critical"
    assert rejected["record_type"] == "MeterRecord"
    assert rejected["record"] == {"silo_id": 1, "wall_ns": 2, "value_kg": 2}
    assert rejected["error"] == "constraint violated"
    assert "fallback" not in rejected


def test_next_batch_is_written_normally_after_a_rejected_record() -> None:
    store = FakeStore(poison=[record(1)])
    writer, in_queue, _ = build(store, max_batch=2)
    for index in range(4):
        in_queue.put(record(index))

    writer.step()
    writer.step()

    assert store.batches == [[record(0)], [record(2), record(3)]]


def test_single_rejected_record_is_logged_and_dropped(
    logs: list[MutableMapping[str, Any]],
) -> None:
    store = FakeStore(poison=[record(1)])
    writer, in_queue, _ = build(store)
    in_queue.put(record(1))

    writer.step()

    assert store.batches == []
    assert [entry["event"] for entry in logs] == [events.DB_RECORD_REJECTED]


def test_rejected_event_end_closes_the_row_as_a_fallback(
    logs: list[MutableMapping[str, Any]],
) -> None:
    store = FakeStore(poison=[closed_event()])
    writer, in_queue, _ = build(store)
    for item in (record(1), closed_event(), record(2)):
        in_queue.put(item)

    writer.step()

    assert store.batches == [[record(1)], [record(2)]]
    assert store.closed_rejected == [closed_event()]
    (rejected,) = logs
    assert rejected["record_type"] == "ClosedEvent"
    assert rejected["record"]["event_id"] == str(UUID(int=1))
    assert rejected["fallback"] == "closed"


def test_rejected_event_end_without_a_row_in_progress_is_only_logged(
    logs: list[MutableMapping[str, Any]],
) -> None:
    store = FakeStore(poison=[closed_event()], close_outcomes=[False])
    writer, in_queue, _ = build(store)
    in_queue.put(closed_event())

    writer.step()

    assert logs[0]["fallback"] == "no_row"


def test_rejected_event_end_whose_fallback_is_rejected_too_is_only_logged(
    logs: list[MutableMapping[str, Any]],
) -> None:
    store = FakeStore(poison=[closed_event()], close_outcomes=[DataStoreError("again")])
    writer, in_queue, _ = build(store)
    in_queue.put(closed_event())
    in_queue.put(record(1))

    writer.step()

    assert store.batches == [[record(1)]]
    assert [entry["fallback"] for entry in logs if "fallback" in entry] == ["failed"]
    assert [entry["event"] for entry in logs] == [events.DB_RECORD_REJECTED]


def test_rejected_started_event_is_logged_without_fallback(
    logs: list[MutableMapping[str, Any]],
) -> None:
    store = FakeStore(poison=[started_event()])
    writer, in_queue, _ = build(store)
    in_queue.put(started_event())
    in_queue.put(record(1))

    writer.step()

    assert store.closed_rejected == []
    assert logs[0]["record_type"] == "StartedEvent"
    assert "fallback" not in logs[0]


def test_transient_error_while_writing_one_by_one_retries_the_record_it_hit() -> None:
    store = FakeStore(poison=[record(1)])
    writer, in_queue, _ = build(store)
    in_queue.put(record(0))
    in_queue.put(record(1))
    in_queue.put(record(2))
    store.failures.extend([DataStoreError("batch"), TransientStoreError("down")])

    writer.step()

    assert store.batches == [[record(0)], [record(2)]]
    assert store.reconnects == 1


def test_skipped_readings_are_logged_once_per_original_batch(
    logs: list[MutableMapping[str, Any]],
) -> None:
    store = FakeStore(poison=[record(2)], duplicates=1)
    writer, in_queue, _ = build(store)
    for index in range(4):
        in_queue.put(record(index))

    writer.step()

    skipped = [entry for entry in logs if entry["event"] == events.DB_READINGS_SKIPPED]
    assert len(skipped) == 1
    assert (skipped[0]["skipped"], skipped[0]["batch_size"]) == (3, 3)


def test_stop_during_outage_while_writing_one_by_one_counts_the_remaining_records(
    logs: list[MutableMapping[str, Any]],
) -> None:
    store = FakeStore()
    in_queue: queue.Queue[WriterRecord] = queue.Queue()
    stop_event = threading.Event()
    writer = Writer(
        in_queue=in_queue,
        store=store,
        stop_event=stop_event,
        retry_delay_s=0,
        wait=lambda _seconds: False,
    )
    for index in range(5):
        in_queue.put(record(index))
    store.failures.extend([DataStoreError("batch"), TransientStoreError("down")])
    stop_event.set()

    writer.run()

    assert not writer.flushed
    assert store.batches == []
    abandoned = [entry for entry in logs if entry["event"] == events.WRITER_ABANDONED]
    assert abandoned[0]["lost_records"] == 5


def test_programming_error_while_writing_one_by_one_is_still_fatal() -> None:
    store = FakeStore()
    writer, in_queue, _ = build(store)
    in_queue.put(record(0))
    in_queue.put(record(1))
    store.failures.extend([DataStoreError("batch"), RuntimeError("syntax")])

    with pytest.raises(RuntimeError, match="syntax"):
        writer.step()
