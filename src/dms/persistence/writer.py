import contextlib
import queue
import threading
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Protocol

import psycopg
import structlog
from psycopg import errors
from psycopg.rows import TupleRow

from dms.domain.records import MeterRecord
from dms.logs import events

MAX_BATCH = 1000
RETRY_DELAY_S = 2.0
GET_TIMEOUT_S = 0.5
NS_PER_US = 1000
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

INSERT_METER_READING_SQL = (
    "INSERT INTO dms.meter_reading (silo_id, t, value_kg) VALUES (%s, %s, %s)"
    " ON CONFLICT DO NOTHING"
)


class TransientStoreError(Exception):
    pass


class RecordStore(Protocol):
    def write(self, records: Sequence[MeterRecord]) -> None: ...

    def reconnect(self) -> None: ...


def timestamp_from_ns(wall_ns: int) -> datetime:
    return EPOCH + timedelta(microseconds=wall_ns // NS_PER_US)


def _is_transient(error: psycopg.Error) -> bool:
    return isinstance(error, psycopg.OperationalError) and not isinstance(error, errors.DiskFull)


class PostgresRecordStore:
    def __init__(
        self,
        connection: psycopg.Connection[TupleRow],
        connect: Callable[[], psycopg.Connection[TupleRow]],
    ) -> None:
        self._connection = connection
        self._connect = connect

    def write(self, records: Sequence[MeterRecord]) -> None:
        rows = [
            (record.silo_id, timestamp_from_ns(record.wall_ns), record.value_kg)
            for record in records
        ]
        try:
            with self._connection.transaction(), self._connection.cursor() as cursor:
                cursor.executemany(INSERT_METER_READING_SQL, rows)
        except psycopg.Error as error:
            if _is_transient(error):
                raise TransientStoreError(str(error)) from error
            raise

    def reconnect(self) -> None:
        with contextlib.suppress(psycopg.Error):
            self._connection.close()
        try:
            self._connection = self._connect()
        except psycopg.Error as error:
            if _is_transient(error):
                raise TransientStoreError(str(error)) from error
            raise


class Writer:
    def __init__(
        self,
        *,
        in_queue: queue.Queue[MeterRecord],
        store: RecordStore,
        stop_event: threading.Event,
        monotonic: Callable[[], float] = time.monotonic,
        max_batch: int = MAX_BATCH,
        retry_delay_s: float = RETRY_DELAY_S,
        wait: Callable[[float], bool] | None = None,
    ) -> None:
        self._in_queue = in_queue
        self._store = store
        self._stop_event = stop_event
        self._monotonic = monotonic
        self._max_batch = max_batch
        self._retry_delay_s = retry_delay_s
        self._wait = wait if wait is not None else stop_event.wait
        self._logger = structlog.get_logger()

    def run(self) -> None:
        try:
            while not self._stop_event.is_set():
                self.step()
            self._flush_remaining()
        except Exception as error:
            self._logger.critical(events.WRITER_FATAL, error=repr(error))
            raise

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

    def _collect_batch(self, first: MeterRecord) -> list[MeterRecord]:
        batch = [first]
        while len(batch) < self._max_batch:
            try:
                batch.append(self._in_queue.get_nowait())
            except queue.Empty:
                break
        return batch

    def _write_with_retry(self, batch: list[MeterRecord]) -> None:
        failed_since: float | None = None
        needs_reconnect = False
        while True:
            try:
                if needs_reconnect:
                    self._store.reconnect()
                    needs_reconnect = False
                self._store.write(batch)
                break
            except TransientStoreError as error:
                if failed_since is None:
                    failed_since = self._monotonic()
                    self._logger.warning(
                        events.DB_WRITE_ERROR, error=str(error), batch_size=len(batch)
                    )
                needs_reconnect = True
                self._wait(self._retry_delay_s)
        if failed_since is not None:
            outage_s = self._monotonic() - failed_since
            self._logger.info(events.DB_WRITE_RECOVERED, outage_s=outage_s)
