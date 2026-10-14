import queue
import threading
from collections.abc import Iterator, MutableMapping, Sequence
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from dms.domain.events import ClosedEvent, StartedEvent
from dms.domain.records import MeterRecord, WriterRecord
from dms.logs import events
from dms.persistence.writer import TransientStoreError, Writer, WriteResult


class FakeStore:
    def __init__(self, failures: list[Exception] | None = None, duplicates: int = 0) -> None:
        self.failures = failures if failures is not None else []
        self.duplicates = duplicates
        self.batches: list[list[WriterRecord]] = []
        self.reconnects = 0

    def write(self, records: Sequence[WriterRecord]) -> WriteResult:
        if self.failures:
            raise self.failures.pop(0)
        self.batches.append(list(records))
        meter_total = sum(isinstance(item, MeterRecord) for item in records)
        return WriteResult(meter_total - self.duplicates, meter_total)

    def reconnect(self) -> None:
        self.reconnects += 1


def record(index: int) -> MeterRecord:
    return MeterRecord(1, index, index)


def build(
    store: FakeStore, max_batch: int = 1000
) -> tuple[Writer, queue.Queue[WriterRecord], threading.Event]:
    in_queue: queue.Queue[WriterRecord] = queue.Queue()
    stop_event = threading.Event()
    clock_values = iter(range(0, 1000, 3))
    writer = Writer(
        in_queue=in_queue,
        store=store,
        stop_event=stop_event,
        max_batch=max_batch,
        retry_delay_s=0,
        wait=lambda _seconds: False,
        monotonic=lambda: float(next(clock_values)),
    )
    return writer, in_queue, stop_event


@pytest.fixture
def logs() -> Iterator[list[MutableMapping[str, Any]]]:
    with capture_logs() as captured:
        yield captured


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
    assert logs[1]["outage_s"] == 3.0


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
    return StartedEvent(UUID(int=1), 1, "dispense", 10, 500, "fresh")


def closed_event() -> ClosedEvent:
    return ClosedEvent(UUID(int=1), 1, "dispense", 10, 500, 20, 400, 10, "fresh", "fresh")


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
