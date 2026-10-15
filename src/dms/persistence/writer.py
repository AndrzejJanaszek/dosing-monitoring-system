import contextlib
import queue
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import NamedTuple, Protocol

import psycopg
import structlog
from psycopg import errors
from psycopg.rows import TupleRow

from dms.domain.events import ClosedEvent, StartedEvent
from dms.domain.records import MeterRecord, WriterRecord
from dms.logs import events

MAX_BATCH = 1000
RETRY_DELAY_S = 2.0
GET_TIMEOUT_S = 0.5
NS_PER_US = 1000
NS_PER_MS = 1_000_000
EVENT_ORIGIN_SIGNAL = "signal"
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

INSERT_METER_READING_SQL = (
    "INSERT INTO dms.meter_reading (silo_id, t, value_kg) VALUES (%s, %s, %s)"
    " ON CONFLICT DO NOTHING"
)

INSERT_EVENT_START_SQL = (
    "INSERT INTO dms.tank_event"
    " (id, tank_id, run_id, type, origin, status, start_at, start_value_kg, start_quality)"
    " VALUES (%s, %s, %s, %s, %s, 'in_progress', %s, %s, %s)"
    " ON CONFLICT (id) DO NOTHING"
)

UPSERT_EVENT_END_SQL = (
    "INSERT INTO dms.tank_event"
    " (id, tank_id, run_id, type, origin, status, start_at, start_value_kg, start_quality,"
    " end_at, end_value_kg, end_quality, duration_ms)"
    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    " ON CONFLICT (id) DO UPDATE SET"
    " status = EXCLUDED.status,"
    " start_at = EXCLUDED.start_at,"
    " start_value_kg = EXCLUDED.start_value_kg,"
    " start_quality = EXCLUDED.start_quality,"
    " end_at = EXCLUDED.end_at,"
    " end_value_kg = EXCLUDED.end_value_kg,"
    " end_quality = EXCLUDED.end_quality,"
    " duration_ms = EXCLUDED.duration_ms"
)


class TransientStoreError(Exception):
    pass


class WriterAbandonedError(Exception):
    def __init__(self, lost_records: int) -> None:
        super().__init__(f"{lost_records} records were not written")
        self.lost_records = lost_records


class WriteResult(NamedTuple):
    meter_inserted: int
    meter_total: int


class RecordStore(Protocol):
    def write(self, records: Sequence[WriterRecord]) -> WriteResult: ...

    def reconnect(self) -> None: ...


def timestamp_from_ns(wall_ns: int) -> datetime:
    return EPOCH + timedelta(microseconds=wall_ns // NS_PER_US)


def duration_ms_from_ns(duration_ns: int) -> int:
    return round(duration_ns / NS_PER_MS)


def _is_transient(error: psycopg.Error) -> bool:
    return isinstance(error, psycopg.OperationalError) and not isinstance(error, errors.DiskFull)


@contextlib.contextmanager
def _transient_errors_translated() -> Iterator[None]:
    try:
        yield
    except psycopg.Error as error:
        if _is_transient(error):
            raise TransientStoreError(str(error)) from error
        raise


class PostgresRecordStore:
    def __init__(
        self,
        connection: psycopg.Connection[TupleRow],
        connect: Callable[[], psycopg.Connection[TupleRow]],
        run_id: int,
    ) -> None:
        self._connection = connection
        self._connect = connect
        self._run_id = run_id

    @property
    def connection(self) -> psycopg.Connection[TupleRow]:
        return self._connection

    def write(self, records: Sequence[WriterRecord]) -> WriteResult:
        meter_rows = [
            (record.silo_id, timestamp_from_ns(record.wall_ns), record.value_kg)
            for record in records
            if isinstance(record, MeterRecord)
        ]
        start_rows = [
            self._start_row(record) for record in records if isinstance(record, StartedEvent)
        ]
        end_rows = [self._end_row(record) for record in records if isinstance(record, ClosedEvent)]
        with (
            _transient_errors_translated(),
            self._connection.transaction(),
            self._connection.cursor() as cursor,
        ):
            meter_inserted = self._execute_group(cursor, INSERT_METER_READING_SQL, meter_rows)
            self._execute_group(cursor, INSERT_EVENT_START_SQL, start_rows)
            self._execute_group(cursor, UPSERT_EVENT_END_SQL, end_rows)
        return WriteResult(meter_inserted, len(meter_rows))

    def _execute_group(
        self,
        cursor: psycopg.Cursor[TupleRow],
        statement: str,
        rows: Sequence[tuple[object, ...]],
    ) -> int:
        if not rows:
            return 0
        cursor.executemany(statement, rows)
        return cursor.rowcount

    def _start_row(self, event: StartedEvent) -> tuple[object, ...]:
        return (
            event.event_id,
            event.tank_id,
            self._run_id,
            event.kind,
            EVENT_ORIGIN_SIGNAL,
            timestamp_from_ns(event.start_wall_ns),
            event.start_value_kg,
            event.start_quality,
        )

    def _end_row(self, event: ClosedEvent) -> tuple[object, ...]:
        return (
            event.event_id,
            event.tank_id,
            self._run_id,
            event.kind,
            EVENT_ORIGIN_SIGNAL,
            event.status,
            timestamp_from_ns(event.start_wall_ns),
            event.start_value_kg,
            event.start_quality,
            timestamp_from_ns(event.end_wall_ns),
            event.end_value_kg,
            event.end_quality,
            None if event.duration_ns is None else duration_ms_from_ns(event.duration_ns),
        )

    def reconnect(self) -> None:
        with contextlib.suppress(psycopg.Error):
            self._connection.close()
        with _transient_errors_translated():
            self._connection = self._connect()


class Writer:
    def __init__(
        self,
        *,
        in_queue: queue.Queue[WriterRecord],
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
        self.flushed = False

    def run(self) -> None:
        try:
            while not self._stop_event.is_set():
                self.step()
            self._flush_remaining()
        except WriterAbandonedError as error:
            lost_records = error.lost_records + self._discard_queue()
            self._logger.error(events.WRITER_ABANDONED, lost_records=lost_records)
            return
        except Exception as error:
            self._logger.critical(events.WRITER_FATAL, error=repr(error))
            raise
        self.flushed = True

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
        failed_since: float | None = None
        needs_reconnect = False
        while True:
            try:
                if needs_reconnect:
                    self._store.reconnect()
                    needs_reconnect = False
                result = self._store.write(batch)
                break
            except TransientStoreError as error:
                if failed_since is None:
                    failed_since = self._monotonic()
                    self._logger.warning(
                        events.DB_WRITE_ERROR, error=str(error), batch_size=len(batch)
                    )
                if self._stop_event.is_set():
                    raise WriterAbandonedError(len(batch)) from error
                needs_reconnect = True
                self._wait(self._retry_delay_s)
        if failed_since is not None:
            outage_s = self._monotonic() - failed_since
            self._logger.info(events.DB_WRITE_RECOVERED, outage_s=outage_s)
        if result.meter_inserted < result.meter_total:
            self._logger.warning(
                events.DB_READINGS_SKIPPED,
                skipped=result.meter_total - result.meter_inserted,
                batch_size=result.meter_total,
            )
