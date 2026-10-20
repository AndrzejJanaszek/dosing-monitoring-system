import queue
import threading
from collections.abc import MutableMapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg
import pytest
from psycopg.rows import TupleRow
from structlog.testing import capture_logs

from dms.acquisition.startup import StartupError, run_startup_sequence
from dms.config.models import (
    AcquisitionConfig,
    BoardConfig,
    InputConfig,
    MeterConfig,
    MeterFormat,
    SiloConfig,
    TankConfig,
)
from dms.domain.events import ClosedEvent, EndQuality, EventKind, StartedEvent, StartQuality
from dms.domain.records import MeterRecord, WriterRecord
from dms.logs import events
from dms.persistence.catalog import (
    SyncResult,
    TankMove,
    start_run,
    stop_run,
    sync_silos,
    sync_tanks,
    tank_identity_violations,
)
from dms.persistence.connection import DatabaseUnreachableError, connect_with_retry
from dms.persistence.record_store import DataStoreError, PostgresRecordStore, timestamp_from_ns
from dms.persistence.writer import Writer
from dms.units import NS_PER_S
from tests.database import connect_as, migrate_as_owner
from tests.fakes import ManualClock

WRITER_ROLE = "dms_writer"
BASE_NS = 1_700_000_000_123_456_000
EVENT_ID = UUID(int=7)
EVENT_START_NS = BASE_NS
EVENT_END_NS = BASE_NS + 12_345_678_000
EVENT_COLUMNS = (
    "id, tank_id, type, origin, status, start_quality, end_quality,"
    " start_at, start_value_kg, end_at, end_value_kg, duration_ms"
)


def silo(silo_id: int, name: str = "Silos") -> SiloConfig:
    return SiloConfig(id=silo_id, name=f"{name} {silo_id}", meter_id=f"m{silo_id}")


def tank(tank_id: int, silo_id: int = 1, name: str = "Zbiornik") -> TankConfig:
    first_pin = 2 * tank_id
    return TankConfig(
        id=tank_id,
        name=f"{name} {tank_id}",
        silo_id=silo_id,
        dispense=InputConfig(pin=first_pin, active_level=0),
        refill=InputConfig(pin=first_pin + 1, active_level=0),
    )


def acquisition_config(
    silos: list[SiloConfig], tanks: list[TankConfig] | None = None
) -> AcquisitionConfig:
    meters = tuple(
        MeterConfig(
            id=item.meter_id,
            port=f"/dev/fake{item.id}",
            baudrate=9600,
            format=MeterFormat.DGTP,
            frame_end="\r\n",
            reconnect_delay_s=5.0,
            silence_timeout_s=5.0,
        )
        for item in silos
    )
    board = (
        BoardConfig(
            id="board",
            port="/dev/fakeboard",
            baudrate=9600,
            frame_end="\r\n",
            reconnect_delay_s=5.0,
            silence_timeout_s=5.0,
        )
        if tanks
        else None
    )
    return AcquisitionConfig(
        meters=meters, silos=tuple(silos), board=board, tanks=tuple(tanks or ())
    )


def rows(connection: psycopg.Connection[TupleRow], query: str) -> list[TupleRow]:
    return connection.execute(query).fetchall()


@pytest.fixture
def writer_connection(fresh_database: str) -> psycopg.Connection[TupleRow]:
    migrate_as_owner(fresh_database)
    connection = connect_as(fresh_database, WRITER_ROLE)
    sync_silos(connection, [silo(1)])
    return connection


def build_store(
    database_url: str, connection: psycopg.Connection[TupleRow]
) -> PostgresRecordStore:
    sync_tanks(connection, [tank(1)])
    run_id = start_run(connection, "1.2.3", {})
    return PostgresRecordStore(connection, lambda: connect_as(database_url, WRITER_ROLE), run_id)


def test_timestamp_keeps_microseconds() -> None:
    assert timestamp_from_ns(BASE_NS) == datetime(2023, 11, 14, 22, 13, 20, 123456, tzinfo=UTC)


def test_sync_silos_adds_renames_and_deactivates(
    writer_connection: psycopg.Connection[TupleRow],
) -> None:
    sync_silos(writer_connection, [silo(1, "Renamed"), silo(2)])
    sync_silos(writer_connection, [silo(2)])

    assert rows(writer_connection, "SELECT id, name, active FROM dms.silo ORDER BY id") == [
        (1, "Renamed 1", False),
        (2, "Silos 2", True),
    ]


def test_sync_silos_reactivates_returning_silo(
    writer_connection: psycopg.Connection[TupleRow],
) -> None:
    sync_silos(writer_connection, [silo(2)])
    sync_silos(writer_connection, [silo(1), silo(2)])

    assert rows(writer_connection, "SELECT id, active FROM dms.silo ORDER BY id") == [
        (1, True),
        (2, True),
    ]


def test_sync_silos_reports_added_reactivated_and_deactivated(
    writer_connection: psycopg.Connection[TupleRow],
) -> None:
    assert sync_silos(writer_connection, [silo(1), silo(2)]) == SyncResult((2,), (), ())
    assert sync_silos(writer_connection, [silo(2), silo(3)]) == SyncResult((3,), (), (1,))
    assert sync_silos(writer_connection, [silo(1), silo(2)]) == SyncResult((), (1,), (3,))


def test_sync_tanks_adds_renames_deactivates_and_reactivates(
    writer_connection: psycopg.Connection[TupleRow],
) -> None:
    assert sync_tanks(writer_connection, [tank(1), tank(2)]) == SyncResult((1, 2), (), ())
    assert sync_tanks(writer_connection, [tank(1, name="Piasek")]) == SyncResult((), (), (2,))
    assert sync_tanks(writer_connection, [tank(1, name="Piasek"), tank(2)]) == SyncResult(
        (), (2,), ()
    )

    assert rows(
        writer_connection, "SELECT id, silo_id, name, active FROM dms.tank ORDER BY id"
    ) == [
        (1, 1, "Piasek 1", True),
        (2, 1, "Zbiornik 2", True),
    ]


def test_tank_in_the_same_silo_is_not_a_violation(
    writer_connection: psycopg.Connection[TupleRow],
) -> None:
    sync_tanks(writer_connection, [tank(1)])

    assert tank_identity_violations(writer_connection, [tank(1), tank(2)]) == []


def test_tank_in_another_silo_is_a_violation_also_when_inactive(
    writer_connection: psycopg.Connection[TupleRow],
) -> None:
    sync_silos(writer_connection, [silo(1), silo(2)])
    sync_tanks(writer_connection, [tank(1), tank(2, silo_id=2)])
    sync_tanks(writer_connection, [tank(2, silo_id=2)])

    violations = tank_identity_violations(
        writer_connection, [tank(2, silo_id=1), tank(1, silo_id=2)]
    )

    assert violations == [TankMove(1, 1, 2), TankMove(2, 2, 1)]


def test_run_is_started_with_config_snapshot_and_stopped(
    writer_connection: psycopg.Connection[TupleRow],
) -> None:
    run_id = start_run(writer_connection, "1.2.3", {"engine": {"tick_interval_s": 1.0}})

    started = rows(
        writer_connection,
        f"SELECT app_version, config, stopped_at FROM dms.run WHERE id = {run_id}",
    )
    assert started == [("1.2.3", {"engine": {"tick_interval_s": 1.0}}, None)]

    stop_run(writer_connection, run_id)

    stopped_at = rows(writer_connection, f"SELECT stopped_at FROM dms.run WHERE id = {run_id}")
    assert stopped_at[0][0] is not None


def test_store_writes_and_ignores_duplicates(
    fresh_database: str, writer_connection: psycopg.Connection[TupleRow]
) -> None:
    store = build_store(fresh_database, writer_connection)
    batch = [MeterRecord(1, BASE_NS, 100), MeterRecord(1, BASE_NS + NS_PER_S, 120)]

    first = store.write(batch)
    second = store.write([*batch, MeterRecord(1, BASE_NS + 2_000_000_000, 140)])

    assert (first.meter_inserted, second.meter_inserted) == (2, 1)
    assert (first.meter_total, second.meter_total) == (2, 3)

    with psycopg.connect(fresh_database) as reader:
        assert rows(reader, "SELECT silo_id, value_kg FROM dms.meter_reading ORDER BY t") == [
            (1, 100),
            (1, 120),
            (1, 140),
        ]


def test_startup_sequence_on_migrated_database(fresh_database: str) -> None:
    migrate_as_owner(fresh_database)
    config = acquisition_config([silo(1), silo(2)])

    with connect_as(fresh_database, WRITER_ROLE) as connection:
        run_id = run_startup_sequence(connection, config)

    with psycopg.connect(fresh_database) as reader:
        assert rows(reader, "SELECT id FROM dms.silo ORDER BY id") == [(1,), (2,)]
        stored_config = rows(reader, f"SELECT config FROM dms.run WHERE id = {run_id}")[0][0]
        assert [item["id"] for item in stored_config["silos"]] == [1, 2]


def test_startup_sequence_stores_tanks_and_board_snapshot(fresh_database: str) -> None:
    migrate_as_owner(fresh_database)
    config = acquisition_config([silo(1)], [tank(1), tank(2)])

    with capture_logs() as logs, connect_as(fresh_database, WRITER_ROLE) as connection:
        run_id = run_startup_sequence(connection, config)

    with psycopg.connect(fresh_database) as reader:
        assert rows(reader, "SELECT id, silo_id, name, active FROM dms.tank ORDER BY id") == [
            (1, 1, "Zbiornik 1", True),
            (2, 1, "Zbiornik 2", True),
        ]
        stored_config = rows(reader, f"SELECT config FROM dms.run WHERE id = {run_id}")[0][0]
        assert stored_config["board"]["id"] == "board"
        assert [item["id"] for item in stored_config["tanks"]] == [1, 2]
    (synced,) = [entry for entry in logs if entry["event"] == events.CATALOG_SYNCED]
    assert synced["silos_added"] == [1]
    assert synced["tanks_added"] == [1, 2]
    assert synced["tanks_deactivated"] == []


def test_startup_sequence_refuses_moved_tanks_and_changes_nothing(fresh_database: str) -> None:
    migrate_as_owner(fresh_database)
    silos = [silo(1), silo(2)]
    with connect_as(fresh_database, WRITER_ROLE) as connection:
        run_startup_sequence(connection, acquisition_config(silos, [tank(1), tank(2)]))
    moved = acquisition_config(silos, [tank(1, silo_id=2), tank(2, silo_id=2), tank(3, silo_id=2)])

    with (
        capture_logs() as logs,
        connect_as(fresh_database, WRITER_ROLE) as connection,
        pytest.raises(StartupError),
    ):
        run_startup_sequence(connection, moved)

    assert [entry["event"] for entry in logs] == [events.CATALOG_IDENTITY_VIOLATION]
    assert logs[0]["tanks"] == [
        {"tank_id": 1, "database_silo_id": 1, "config_silo_id": 2},
        {"tank_id": 2, "database_silo_id": 1, "config_silo_id": 2},
    ]
    with psycopg.connect(fresh_database) as reader:
        assert rows(reader, "SELECT count(*) FROM dms.run") == [(1,)]
        assert rows(reader, "SELECT id FROM dms.tank ORDER BY id") == [(1,), (2,)]


def test_inactive_tank_returning_under_another_silo_is_refused(fresh_database: str) -> None:
    migrate_as_owner(fresh_database)
    silos = [silo(1), silo(2)]
    with connect_as(fresh_database, WRITER_ROLE) as connection:
        run_startup_sequence(connection, acquisition_config(silos, [tank(1), tank(2)]))
        run_startup_sequence(connection, acquisition_config(silos, [tank(2)]))

    with connect_as(fresh_database, WRITER_ROLE) as connection, pytest.raises(StartupError):
        run_startup_sequence(connection, acquisition_config(silos, [tank(1, silo_id=2)]))


def test_inactive_tank_returning_under_the_same_silo_is_reactivated(fresh_database: str) -> None:
    migrate_as_owner(fresh_database)
    silos = [silo(1)]
    with connect_as(fresh_database, WRITER_ROLE) as connection:
        run_startup_sequence(connection, acquisition_config(silos, [tank(1), tank(2)]))
        run_startup_sequence(connection, acquisition_config(silos, [tank(2)]))
        with capture_logs() as logs:
            run_startup_sequence(connection, acquisition_config(silos, [tank(1), tank(2)]))

    (synced,) = [entry for entry in logs if entry["event"] == events.CATALOG_SYNCED]
    assert synced["tanks_reactivated"] == [1]


def test_startup_sequence_refuses_database_without_migrations(
    fresh_database: str,
) -> None:
    with (
        capture_logs() as logs,
        connect_as(fresh_database, WRITER_ROLE) as connection,
        pytest.raises(StartupError),
    ):
        run_startup_sequence(connection, acquisition_config([silo(1)]))

    assert [entry["event"] for entry in logs] == [events.DB_SCHEMA_INCOMPATIBLE]


def test_connect_with_retry_gives_up_after_timeout() -> None:
    clock = ManualClock()
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.advance(seconds)

    with pytest.raises(DatabaseUnreachableError, match="not reachable"):
        connect_with_retry(
            "host=127.0.0.1 port=1 dbname=x user=y connect_timeout=1",
            timeout_s=3,
            retry_interval_s=1,
            sleep=sleep,
            clock=clock,
        )

    assert sum(sleeps) >= 2


def test_connect_with_retry_connects_when_database_is_up(fresh_database: str) -> None:
    with capture_logs() as logs:
        connection = connect_with_retry(fresh_database)
    connection.close()

    assert [entry["event"] for entry in logs] == [events.DB_CONNECTED]


def test_writer_survives_terminated_connection(
    fresh_database: str, writer_connection: psycopg.Connection[TupleRow]
) -> None:
    store = build_store(fresh_database, writer_connection)
    in_queue: queue.Queue[WriterRecord] = queue.Queue()
    writer = Writer(
        in_queue=in_queue,
        store=store,
        stop_event=threading.Event(),
        retry_delay_s=0,
        wait=lambda _seconds: False,
    )
    in_queue.put(MeterRecord(1, BASE_NS, 100))
    writer.step()
    backend_pid = writer_connection.info.backend_pid
    with psycopg.connect(fresh_database, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(%s)", [backend_pid])
    in_queue.put(MeterRecord(1, BASE_NS + NS_PER_S, 120))
    captured: list[MutableMapping[str, Any]]
    with capture_logs() as captured:
        writer.step()

    with psycopg.connect(fresh_database) as reader:
        assert rows(reader, "SELECT value_kg FROM dms.meter_reading ORDER BY t") == [
            (100,),
            (120,),
        ]
    assert [entry["event"] for entry in captured] == [
        events.DB_WRITE_ERROR,
        events.DB_WRITE_RECOVERED,
    ]


def started(event_id: UUID = EVENT_ID, *, orphaned: bool = False) -> StartedEvent:
    if orphaned:
        return StartedEvent(
            event_id=event_id,
            tank_id=1,
            kind=EventKind.DISPENSE,
            start_wall_ns=EVENT_START_NS,
            start_value_kg=None,
            start_quality=StartQuality.UNKNOWN,
        )
    return StartedEvent(
        event_id=event_id,
        tank_id=1,
        kind=EventKind.DISPENSE,
        start_wall_ns=EVENT_START_NS,
        start_value_kg=1000,
        start_quality=StartQuality.FRESH,
    )


def closed(event_id: UUID = EVENT_ID, *, stale_end: bool = False) -> ClosedEvent:
    return ClosedEvent(
        event_id=event_id,
        tank_id=1,
        kind=EventKind.DISPENSE,
        start_wall_ns=EVENT_START_NS,
        start_value_kg=1000,
        end_wall_ns=EVENT_END_NS,
        end_value_kg=None if stale_end else 400,
        duration_ns=12_345_678_000,
        start_quality=StartQuality.FRESH,
        end_quality=EndQuality.STALE_READING if stale_end else EndQuality.FRESH,
    )


def event_rows(database_url: str) -> list[TupleRow]:
    with psycopg.connect(database_url) as reader:
        return rows(reader, f"SELECT {EVENT_COLUMNS} FROM dms.tank_event ORDER BY start_at, id")


def completed_row() -> tuple[object, ...]:
    return (
        EVENT_ID,
        1,
        "dispense",
        "signal",
        "completed",
        "fresh",
        "fresh",
        timestamp_from_ns(EVENT_START_NS),
        1000,
        timestamp_from_ns(EVENT_END_NS),
        400,
        12_346,
    )


def test_event_start_is_stored_as_in_progress(
    fresh_database: str, writer_connection: psycopg.Connection[TupleRow]
) -> None:
    store = build_store(fresh_database, writer_connection)

    store.write([started()])

    assert event_rows(fresh_database) == [
        (
            EVENT_ID,
            1,
            "dispense",
            "signal",
            "in_progress",
            "fresh",
            None,
            timestamp_from_ns(EVENT_START_NS),
            1000,
            None,
            None,
            None,
        )
    ]


def test_event_end_completes_the_started_row_with_the_run_id(
    fresh_database: str, writer_connection: psycopg.Connection[TupleRow]
) -> None:
    store = build_store(fresh_database, writer_connection)

    store.write([started()])
    store.write([closed()])

    assert event_rows(fresh_database) == [completed_row()]
    with psycopg.connect(fresh_database) as reader:
        assert rows(reader, "SELECT count(*) FROM dms.tank_event WHERE run_id = 1") == [(1,)]


def test_event_end_without_start_creates_the_row(
    fresh_database: str, writer_connection: psycopg.Connection[TupleRow]
) -> None:
    store = build_store(fresh_database, writer_connection)

    store.write([closed()])

    assert event_rows(fresh_database) == [completed_row()]


def test_event_end_before_start_in_one_batch_ends_complete(
    fresh_database: str, writer_connection: psycopg.Connection[TupleRow]
) -> None:
    store = build_store(fresh_database, writer_connection)

    store.write([closed(), started()])

    assert event_rows(fresh_database) == [completed_row()]


def test_repeated_batch_is_idempotent(
    fresh_database: str, writer_connection: psycopg.Connection[TupleRow]
) -> None:
    store = build_store(fresh_database, writer_connection)
    batch: list[WriterRecord] = [started(), closed(), MeterRecord(1, BASE_NS, 100)]

    store.write(batch)
    result = store.write(batch)

    assert event_rows(fresh_database) == [completed_row()]
    assert result.meter_inserted == 0


def test_incomplete_event_stores_both_qualities_and_empty_value(
    fresh_database: str, writer_connection: psycopg.Connection[TupleRow]
) -> None:
    store = build_store(fresh_database, writer_connection)

    store.write([started(), closed(stale_end=True)])

    (row,) = event_rows(fresh_database)
    assert row[4:7] == ("incomplete", "fresh", "stale_reading")
    assert row[10] is None


def test_orphaned_event_stores_empty_start_value(
    fresh_database: str, writer_connection: psycopg.Connection[TupleRow]
) -> None:
    store = build_store(fresh_database, writer_connection)

    store.write([started(orphaned=True)])

    (row,) = event_rows(fresh_database)
    assert row[4:7] == ("in_progress", "unknown", None)
    assert row[8] is None


def test_orphaned_event_closed_by_lost_signals_keeps_both_qualities(
    fresh_database: str, writer_connection: psycopg.Connection[TupleRow]
) -> None:
    store = build_store(fresh_database, writer_connection)
    lost = ClosedEvent(
        event_id=EVENT_ID,
        tank_id=1,
        kind=EventKind.DISPENSE,
        start_wall_ns=EVENT_START_NS,
        start_value_kg=None,
        end_wall_ns=EVENT_END_NS,
        end_value_kg=None,
        duration_ns=None,
        start_quality=StartQuality.UNKNOWN,
        end_quality=EndQuality.SIGNAL_LOST,
    )

    store.write([started(orphaned=True), lost])

    (row,) = event_rows(fresh_database)
    assert row[4:7] == ("incomplete", "unknown", "signal_lost")


def test_batch_mixing_readings_and_events_is_one_transaction(
    fresh_database: str, writer_connection: psycopg.Connection[TupleRow]
) -> None:
    store = build_store(fresh_database, writer_connection)
    violating = ClosedEvent(
        event_id=UUID(int=9),
        tank_id=1,
        kind=EventKind.DISPENSE,
        start_wall_ns=BASE_NS,
        start_value_kg=1,
        end_wall_ns=BASE_NS,
        end_value_kg=1,
        duration_ns=-2_000_000,
        start_quality=StartQuality.FRESH,
        end_quality=EndQuality.FRESH,
    )

    with pytest.raises(DataStoreError):
        store.write([MeterRecord(1, BASE_NS, 100), started(), violating])

    with psycopg.connect(fresh_database) as reader:
        assert rows(reader, "SELECT count(*) FROM dms.meter_reading") == [(0,)]
        assert rows(reader, "SELECT count(*) FROM dms.tank_event") == [(0,)]


def test_event_end_may_precede_start_on_the_wall_clock(
    fresh_database: str, writer_connection: psycopg.Connection[TupleRow]
) -> None:
    store = build_store(fresh_database, writer_connection)
    stepped_back = ClosedEvent(
        event_id=EVENT_ID,
        tank_id=1,
        kind=EventKind.DISPENSE,
        start_wall_ns=BASE_NS,
        start_value_kg=1,
        end_wall_ns=BASE_NS - 5_000_000_000,
        end_value_kg=1,
        duration_ns=1000,
        start_quality=StartQuality.FRESH,
        end_quality=EndQuality.FRESH,
    )

    store.write([stepped_back])

    assert len(event_rows(fresh_database)) == 1


def seed_run(connection: psycopg.Connection[TupleRow], started_at_ns: int) -> int:
    run_id = start_run(connection, "1.2.3", {})
    connection.execute(
        "UPDATE dms.run SET started_at = %s WHERE id = %s",
        [timestamp_from_ns(started_at_ns), run_id],
    )
    return run_id


def seed_reading(connection: psycopg.Connection[TupleRow], silo_id: int, wall_ns: int) -> None:
    connection.execute(
        "INSERT INTO dms.meter_reading (silo_id, t, value_kg) VALUES (%s, %s, 100)",
        [silo_id, timestamp_from_ns(wall_ns)],
    )


def seed_event(
    connection: psycopg.Connection[TupleRow],
    run_id: int,
    event_id: UUID,
    start_ns: int,
    *,
    tank_id: int = 1,
    status: str = "in_progress",
    start_quality: str = "fresh",
) -> None:
    ended = status != "in_progress"
    connection.execute(
        "INSERT INTO dms.tank_event (id, tank_id, run_id, type, origin, status, start_at,"
        " start_value_kg, start_quality, end_at, end_value_kg, end_quality, duration_ms)"
        " VALUES (%s, %s, %s, 'dispense', 'signal', %s, %s, %s, %s, %s, %s, %s, %s)",
        [
            event_id,
            tank_id,
            run_id,
            status,
            timestamp_from_ns(start_ns),
            None if start_quality == "unknown" else 1000,
            start_quality,
            timestamp_from_ns(start_ns + NS_PER_S) if ended else None,
            400 if status == "completed" else None,
            None if not ended else "fresh" if status == "completed" else "signal_lost",
            1000 if status == "completed" else None,
        ],
    )


@pytest.fixture
def crashed_run(
    writer_connection: psycopg.Connection[TupleRow],
) -> tuple[psycopg.Connection[TupleRow], int]:
    sync_tanks(writer_connection, [tank(1)])
    return writer_connection, seed_run(writer_connection, BASE_NS)


def restart(connection: psycopg.Connection[TupleRow]) -> int:
    return run_startup_sequence(connection, acquisition_config([silo(1)], [tank(1)]))


def test_restart_closes_event_in_progress_at_the_last_reading_before_the_new_run(
    fresh_database: str, crashed_run: tuple[psycopg.Connection[TupleRow], int]
) -> None:
    connection, run_id = crashed_run
    seed_event(connection, run_id, EVENT_ID, BASE_NS + 10 * NS_PER_S)
    seed_reading(connection, 1, BASE_NS + 5 * NS_PER_S)
    seed_reading(connection, 1, BASE_NS + 20 * NS_PER_S)
    seed_reading(connection, 1, BASE_NS + 30 * NS_PER_S)
    connection.execute(
        "INSERT INTO dms.meter_reading (silo_id, t, value_kg)"
        " VALUES (1, now() + interval '1 day', 100)"
    )

    restart(connection)

    (row,) = event_rows(fresh_database)
    assert row[4:7] == ("incomplete", "fresh", "service_crashed")
    assert row[9] == timestamp_from_ns(BASE_NS + 30 * NS_PER_S)
    assert (row[10], row[11]) == (None, None)


def test_restart_closes_event_without_readings_with_a_zero_length_interval(
    fresh_database: str, crashed_run: tuple[psycopg.Connection[TupleRow], int]
) -> None:
    connection, run_id = crashed_run
    seed_event(connection, run_id, EVENT_ID, BASE_NS + 10 * NS_PER_S)
    seed_reading(connection, 1, BASE_NS + 5 * NS_PER_S)

    restart(connection)

    (row,) = event_rows(fresh_database)
    assert row[7] == row[9] == timestamp_from_ns(BASE_NS + 10 * NS_PER_S)


def test_restart_ignores_readings_of_other_silos(
    fresh_database: str, crashed_run: tuple[psycopg.Connection[TupleRow], int]
) -> None:
    connection, run_id = crashed_run
    sync_silos(connection, [silo(1), silo(2)])
    seed_event(connection, run_id, EVENT_ID, BASE_NS + 10 * NS_PER_S)
    seed_reading(connection, 1, BASE_NS + 20 * NS_PER_S)
    seed_reading(connection, 2, BASE_NS + 40 * NS_PER_S)

    restart(connection)

    (row,) = event_rows(fresh_database)
    assert row[9] == timestamp_from_ns(BASE_NS + 20 * NS_PER_S)


def test_restart_closes_an_orphaned_event_in_progress(
    fresh_database: str, crashed_run: tuple[psycopg.Connection[TupleRow], int]
) -> None:
    connection, run_id = crashed_run
    seed_event(connection, run_id, EVENT_ID, BASE_NS, start_quality="unknown")

    restart(connection)

    (row,) = event_rows(fresh_database)
    assert row[4:7] == ("incomplete", "unknown", "service_crashed")
    assert row[8] is None


def test_restart_leaves_finished_events_alone(
    fresh_database: str, crashed_run: tuple[psycopg.Connection[TupleRow], int]
) -> None:
    connection, run_id = crashed_run
    seed_event(connection, run_id, UUID(int=1), BASE_NS, status="completed")
    seed_event(connection, run_id, UUID(int=2), BASE_NS + NS_PER_S, status="incomplete")
    before = event_rows(fresh_database)

    with capture_logs() as logs:
        restart(connection)

    assert event_rows(fresh_database) == before
    assert [entry for entry in logs if entry["event"] == events.EVENT_CRASH_CLOSED] == []


def test_restart_leaves_the_interrupted_run_without_stop_time(
    fresh_database: str, crashed_run: tuple[psycopg.Connection[TupleRow], int]
) -> None:
    connection, run_id = crashed_run
    seed_event(connection, run_id, EVENT_ID, BASE_NS)

    new_run_id = restart(connection)

    with psycopg.connect(fresh_database) as reader:
        assert rows(reader, "SELECT id, stopped_at FROM dms.run ORDER BY id") == [
            (run_id, None),
            (new_run_id, None),
        ]


def test_restart_keeps_the_end_of_an_older_event_inside_its_own_run(
    fresh_database: str, crashed_run: tuple[psycopg.Connection[TupleRow], int]
) -> None:
    connection, first_run_id = crashed_run
    seed_run(connection, BASE_NS + 100 * NS_PER_S)
    seed_event(connection, first_run_id, EVENT_ID, BASE_NS + 10 * NS_PER_S)
    seed_reading(connection, 1, BASE_NS + 20 * NS_PER_S)
    seed_reading(connection, 1, BASE_NS + 150 * NS_PER_S)

    restart(connection)

    (row,) = event_rows(fresh_database)
    assert row[9] == timestamp_from_ns(BASE_NS + 20 * NS_PER_S)


def test_restart_logs_the_closed_events_once(
    crashed_run: tuple[psycopg.Connection[TupleRow], int],
) -> None:
    connection, run_id = crashed_run
    seed_event(connection, run_id, UUID(int=1), BASE_NS)
    seed_event(connection, run_id, UUID(int=2), BASE_NS + NS_PER_S)

    with capture_logs() as logs:
        restart(connection)

    (crash_closed,) = [entry for entry in logs if entry["event"] == events.EVENT_CRASH_CLOSED]
    assert crash_closed["log_level"] == "error"
    assert crash_closed["count"] == 2
    assert sorted(item["event_id"] for item in crash_closed["events"]) == [
        str(UUID(int=1)),
        str(UUID(int=2)),
    ]
    assert {item["tank_id"] for item in crash_closed["events"]} == {1}


def build_writer(store: PostgresRecordStore) -> tuple[Writer, queue.Queue[WriterRecord]]:
    in_queue: queue.Queue[WriterRecord] = queue.Queue()
    writer = Writer(
        in_queue=in_queue,
        store=store,
        stop_event=threading.Event(),
        retry_delay_s=0,
        wait=lambda _seconds: False,
    )
    return writer, in_queue


def test_batch_with_a_rejected_record_stores_the_other_records_and_keeps_going(
    fresh_database: str, writer_connection: psycopg.Connection[TupleRow]
) -> None:
    writer, in_queue = build_writer(build_store(fresh_database, writer_connection))
    unknown_tank = ClosedEvent(
        event_id=UUID(int=9),
        tank_id=99,
        kind=EventKind.DISPENSE,
        start_wall_ns=BASE_NS,
        start_value_kg=1,
        end_wall_ns=BASE_NS,
        end_value_kg=1,
        duration_ns=1000,
        start_quality=StartQuality.FRESH,
        end_quality=EndQuality.FRESH,
    )
    for item in (MeterRecord(1, BASE_NS, 100), started(), unknown_tank):
        in_queue.put(item)

    with capture_logs() as logs:
        writer.step()
    in_queue.put(MeterRecord(1, BASE_NS + NS_PER_S, 110))
    writer.step()

    with psycopg.connect(fresh_database) as reader:
        assert rows(reader, "SELECT value_kg FROM dms.meter_reading ORDER BY t") == [
            (100,),
            (110,),
        ]
    assert [row[4] for row in event_rows(fresh_database)] == ["in_progress"]
    (rejected,) = [entry for entry in logs if entry["event"] == events.DB_RECORD_REJECTED]
    assert rejected["log_level"] == "critical"
    assert rejected["record_type"] == "ClosedEvent"
    assert rejected["record"]["tank_id"] == 99
    assert rejected["fallback"] == "no_row"


def test_rejected_event_end_closes_the_row_in_progress_as_record_rejected(
    fresh_database: str, writer_connection: psycopg.Connection[TupleRow]
) -> None:
    store = build_store(fresh_database, writer_connection)
    writer, in_queue = build_writer(store)
    store.write([started()])
    violating = ClosedEvent(
        event_id=EVENT_ID,
        tank_id=1,
        kind=EventKind.DISPENSE,
        start_wall_ns=EVENT_START_NS,
        start_value_kg=1000,
        end_wall_ns=EVENT_END_NS,
        end_value_kg=400,
        duration_ns=-2_000_000,
        start_quality=StartQuality.FRESH,
        end_quality=EndQuality.FRESH,
    )
    in_queue.put(violating)

    with capture_logs() as logs:
        writer.step()

    (row,) = event_rows(fresh_database)
    assert row[4:7] == ("incomplete", "fresh", "record_rejected")
    assert row[9] == timestamp_from_ns(EVENT_END_NS)
    assert (row[10], row[11]) == (None, None)
    (rejected,) = [entry for entry in logs if entry["event"] == events.DB_RECORD_REJECTED]
    assert rejected["fallback"] == "closed"


def test_rejected_event_end_does_not_touch_a_row_that_is_not_in_progress(
    fresh_database: str, writer_connection: psycopg.Connection[TupleRow]
) -> None:
    store = build_store(fresh_database, writer_connection)
    writer, in_queue = build_writer(store)
    store.write([started(), closed()])
    before = event_rows(fresh_database)
    violating = ClosedEvent(
        event_id=EVENT_ID,
        tank_id=1,
        kind=EventKind.DISPENSE,
        start_wall_ns=EVENT_START_NS,
        start_value_kg=1000,
        end_wall_ns=EVENT_END_NS,
        end_value_kg=400,
        duration_ns=-2_000_000,
        start_quality=StartQuality.FRESH,
        end_quality=EndQuality.FRESH,
    )
    in_queue.put(violating)

    writer.step()

    assert event_rows(fresh_database) == before
