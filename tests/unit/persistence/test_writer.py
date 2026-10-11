import queue
import threading
from collections.abc import Iterator, MutableMapping, Sequence
from typing import Any

import pytest
from structlog.testing import capture_logs

from dms.domain.records import MeterRecord
from dms.logs import events
from dms.persistence.writer import TransientStoreError, Writer


class FakeStore:
    def __init__(self, failures: list[Exception] | None = None) -> None:
        self.failures = failures if failures is not None else []
        self.batches: list[list[MeterRecord]] = []
        self.reconnects = 0

    def write(self, records: Sequence[MeterRecord]) -> None:
        if self.failures:
            raise self.failures.pop(0)
        self.batches.append(list(records))

    def reconnect(self) -> None:
        self.reconnects += 1


def record(index: int) -> MeterRecord:
    return MeterRecord(1, index, index)


def build(
    store: FakeStore, max_batch: int = 1000
) -> tuple[Writer, queue.Queue[MeterRecord], threading.Event]:
    in_queue: queue.Queue[MeterRecord] = queue.Queue()
    stop_event = threading.Event()
    clock_values = iter(range(0, 1000, 3))
    writer = Writer(
        in_queue=in_queue,
        store=store,
        stop_event=stop_event,
        max_batch=max_batch,
        retry_delay_s=0,
        sleep=lambda _seconds: None,
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
