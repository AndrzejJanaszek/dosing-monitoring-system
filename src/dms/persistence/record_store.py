import contextlib
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import NamedTuple, Protocol

import psycopg
from psycopg import errors
from psycopg.rows import TupleRow

from dms.domain.events import ClosedEvent, StartedEvent
from dms.domain.records import MeterRecord, WriterRecord
from dms.units import NS_PER_MS, NS_PER_US

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

CLOSE_REJECTED_EVENT_SQL = (
    "UPDATE dms.tank_event SET status = 'incomplete', end_at = %s,"
    " end_quality = 'record_rejected', end_value_kg = NULL, duration_ms = NULL"
    " WHERE id = %s AND status = 'in_progress'"
)


class EventOrigin(StrEnum):
    SIGNAL = "signal"


class TransientStoreError(Exception):
    pass


class DataStoreError(Exception):
    pass


class WriteResult(NamedTuple):
    meter_inserted: int
    meter_total: int


class RecordStore(Protocol):
    def write(self, records: Sequence[WriterRecord]) -> WriteResult: ...

    def close_rejected_event(self, event: ClosedEvent) -> bool: ...

    def reconnect(self) -> None: ...


def timestamp_from_ns(wall_ns: int) -> datetime:
    return EPOCH + timedelta(microseconds=wall_ns // NS_PER_US)


def duration_ms_from_ns(duration_ns: int) -> int:
    return round(duration_ns / NS_PER_MS)


def _is_transient(error: psycopg.Error) -> bool:
    return isinstance(error, psycopg.OperationalError) and not isinstance(error, errors.DiskFull)


def _is_data_error(error: psycopg.Error) -> bool:
    return isinstance(error, psycopg.IntegrityError | psycopg.DataError)


@contextlib.contextmanager
def _store_errors_translated() -> Iterator[None]:
    try:
        yield
    except psycopg.Error as error:
        if _is_transient(error):
            raise TransientStoreError(str(error)) from error
        if _is_data_error(error):
            raise DataStoreError(str(error)) from error
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
            _store_errors_translated(),
            self._connection.transaction(),
            self._connection.cursor() as cursor,
        ):
            meter_inserted = self._execute_group(cursor, INSERT_METER_READING_SQL, meter_rows)
            self._execute_group(cursor, INSERT_EVENT_START_SQL, start_rows)
            self._execute_group(cursor, UPSERT_EVENT_END_SQL, end_rows)
        return WriteResult(meter_inserted, len(meter_rows))

    def close_rejected_event(self, event: ClosedEvent) -> bool:
        with (
            _store_errors_translated(),
            self._connection.transaction(),
            self._connection.cursor() as cursor,
        ):
            cursor.execute(
                CLOSE_REJECTED_EVENT_SQL, [timestamp_from_ns(event.end_wall_ns), event.event_id]
            )
            return cursor.rowcount == 1

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
            EventOrigin.SIGNAL,
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
            EventOrigin.SIGNAL,
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
        with _store_errors_translated():
            self._connection = self._connect()
