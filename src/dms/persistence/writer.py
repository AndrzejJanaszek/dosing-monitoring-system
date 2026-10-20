import dataclasses
import functools
import queue
import threading
from collections.abc import Callable
from enum import StrEnum
from typing import Any
from uuid import UUID

import structlog

from dms.clock import Clock, SystemClock
from dms.domain.events import ClosedEvent
from dms.domain.records import WriterRecord
from dms.logs import events
from dms.persistence.record_store import (
    DataStoreError,
    RecordStore,
    TransientStoreError,
    WriteResult,
)
from dms.units import NS_PER_S

MAX_BATCH = 1000
RETRY_DELAY_S = 2.0
GET_TIMEOUT_S = 0.5

logger = structlog.get_logger()


class RejectedFallback(StrEnum):
    CLOSED = "closed"
    NO_ROW = "no_row"
    FAILED = "failed"


class WriterAbandonedError(Exception):
    def __init__(self, lost_records: int) -> None:
        super().__init__(f"{lost_records} records were not written")
        self.lost_records = lost_records


def _record_fields(record: WriterRecord) -> dict[str, Any]:
    fields = {field.name: getattr(record, field.name) for field in dataclasses.fields(record)}
    return {
        name: str(value) if isinstance(value, UUID) else value for name, value in fields.items()
    }


class Writer:
    def __init__(
        self,
        *,
        in_queue: queue.Queue[WriterRecord],
        store: RecordStore,
        stop_event: threading.Event,
        clock: Clock | None = None,
        max_batch: int = MAX_BATCH,
        retry_delay_s: float = RETRY_DELAY_S,
        wait: Callable[[float], bool] | None = None,
    ) -> None:
        self._in_queue = in_queue
        self._store = store
        self._stop_event = stop_event
        self._clock = clock if clock is not None else SystemClock()
        self._max_batch = max_batch
        self._retry_delay_s = retry_delay_s
        self._wait = wait if wait is not None else stop_event.wait
        self._flushed = False

    @property
    def flushed(self) -> bool:
        return self._flushed

    def run(self) -> None:
        try:
            while not self._stop_event.is_set():
                self.step()
            self._flush_remaining()
        except WriterAbandonedError as error:
            lost_records = error.lost_records + self._discard_queue()
            logger.error(events.WRITER_ABANDONED, lost_records=lost_records)
            return
        except Exception as error:
            logger.critical(events.WRITER_FATAL, error=str(error), exc_info=True)
            raise
        self._flushed = True

    def step(self) -> None:
        try:
            first = self._in_queue.get(timeout=GET_TIMEOUT_S)
        except queue.Empty:
            return
        self._write_with_retry(self._collect_batch(first))

    def _flush_remaining(self) -> None:
        while True:
            try:
                first = self._in_queue.get_nowait()
            except queue.Empty:
                return
            self._write_with_retry(self._collect_batch(first))

    def _discard_queue(self) -> int:
        discarded = 0
        while True:
            try:
                self._in_queue.get_nowait()
            except queue.Empty:
                return discarded
            discarded += 1

    def _collect_batch(self, first: WriterRecord) -> list[WriterRecord]:
        batch = [first]
        while len(batch) < self._max_batch:
            try:
                batch.append(self._in_queue.get_nowait())
            except queue.Empty:
                break
        return batch

    def _write_with_retry(self, batch: list[WriterRecord]) -> None:
        try:
            result = self._retrying(functools.partial(self._store.write, batch), len(batch))
        except DataStoreError:
            self._write_one_by_one(batch)
            return
        self._log_skipped_readings(result)

    def _write_one_by_one(self, batch: list[WriterRecord]) -> None:
        readings_inserted = 0
        readings_total = 0

        for index, item in enumerate(batch):
            try:
                result = self._write_or_reject(item)
            except WriterAbandonedError as error:
                remaining = len(batch) - index - 1
                raise WriterAbandonedError(error.lost_records + remaining) from error

            readings_inserted += result.readings_inserted
            readings_total += result.readings_total

        self._log_skipped_readings(WriteResult(readings_inserted, readings_total))

    def _write_or_reject(self, item: WriterRecord) -> WriteResult:
        try:
            return self._retrying(functools.partial(self._store.write, [item]), 1)
        except DataStoreError as error:
            self._reject(item, error)
            return WriteResult(0, 0)

    def _reject(self, item: WriterRecord, error: DataStoreError) -> None:
        fallback = self._close_rejected_event(item) if isinstance(item, ClosedEvent) else None

        fields: dict[str, Any] = {
            "record_type": type(item).__name__,
            "record": _record_fields(item),
            "error": str(error),
        }
        if fallback is not None:
            fields["fallback"] = fallback
        logger.critical(events.DB_RECORD_REJECTED, **fields)

    def _close_rejected_event(self, event: ClosedEvent) -> RejectedFallback:
        try:
            closed = self._retrying(functools.partial(self._store.close_rejected_event, event), 1)
        except DataStoreError:
            return RejectedFallback.FAILED

        return RejectedFallback.CLOSED if closed else RejectedFallback.NO_ROW

    def _retrying[T](self, action: Callable[[], T], record_count: int) -> T:
        failed_since_ns: int | None = None
        needs_reconnect = False
        while True:
            try:
                if needs_reconnect:
                    self._store.reconnect()
                    needs_reconnect = False
                outcome = action()
                break
            except TransientStoreError as error:
                if failed_since_ns is None:
                    failed_since_ns = self._clock.mono_ns()
                    logger.warning(
                        events.DB_WRITE_ERROR, error=str(error), batch_size=record_count
                    )
                if self._stop_event.is_set():
                    raise WriterAbandonedError(record_count) from error
                needs_reconnect = True
                self._wait(self._retry_delay_s)
        if failed_since_ns is not None:
            outage_s = (self._clock.mono_ns() - failed_since_ns) / NS_PER_S
            logger.info(events.DB_WRITE_RECOVERED, outage_s=outage_s)
        return outcome

    def _log_skipped_readings(self, result: WriteResult) -> None:
        if result.readings_inserted < result.readings_total:
            logger.warning(
                events.DB_READINGS_SKIPPED,
                skipped=result.readings_total - result.readings_inserted,
                batch_size=result.readings_total,
            )
