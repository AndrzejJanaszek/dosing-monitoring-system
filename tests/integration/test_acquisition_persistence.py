import queue
import threading
from collections.abc import MutableMapping
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from psycopg.rows import TupleRow
from structlog.testing import capture_logs

from dms.acquisition.startup import run_startup_sequence
from dms.config.models import AcquisitionConfig, MeterConfig, SiloConfig
from dms.domain.records import MeterRecord
from dms.logs import events
from dms.persistence.catalog import start_run, stop_run, sync_silos
from dms.persistence.connection import StartupError, connect_with_retry
from dms.persistence.writer import PostgresRecordStore, Writer, timestamp_from_ns
from tests.database import connect_as, migrate_as_owner

WRITER_ROLE = "dms_writer"
BASE_NS = 1_700_000_000_123_456_000


def silo(silo_id: int, name: str = "Silos") -> SiloConfig:
    return SiloConfig(id=silo_id, name=f"{name} {silo_id}", meter=f"m{silo_id}")


def acquisition_config(silos: list[SiloConfig]) -> AcquisitionConfig:
    meters = tuple(
        MeterConfig(
            id=item.meter,
            port=f"/dev/fake{item.id}",
            baudrate=9600,
            format="dgtp",
            frame_end="\r\n",
            reconnect_delay_s=5.0,
            silence_timeout_s=5.0,
        )
        for item in silos
    )
    return AcquisitionConfig(meters=meters, silos=tuple(silos))


def rows(connection: psycopg.Connection[TupleRow], query: str) -> list[TupleRow]:
    return connection.execute(query).fetchall()


@pytest.fixture
def writer_connection(fresh_database: str) -> psycopg.Connection[TupleRow]:
    migrate_as_owner(fresh_database)
    connection = connect_as(fresh_database, WRITER_ROLE)
    sync_silos(connection, [silo(1)])
    return connection


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
    store = PostgresRecordStore(writer_connection, lambda: connect_as(fresh_database, WRITER_ROLE))
    batch = [MeterRecord(1, BASE_NS, 100), MeterRecord(1, BASE_NS + 1_000_000_000, 120)]

    first_inserted = store.write(batch)
    second_inserted = store.write([*batch, MeterRecord(1, BASE_NS + 2_000_000_000, 140)])

    assert (first_inserted, second_inserted) == (2, 1)

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
    now = [0.0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    with pytest.raises(StartupError, match="not reachable"):
        connect_with_retry(
            "host=127.0.0.1 port=1 dbname=x user=y connect_timeout=1",
            timeout_s=3,
            retry_interval_s=1,
            sleep=sleep,
            monotonic=lambda: now[0],
        )

    assert now[0] >= 2


def test_connect_with_retry_connects_when_database_is_up(fresh_database: str) -> None:
    with capture_logs() as logs:
        connection = connect_with_retry(fresh_database)
    connection.close()

    assert [entry["event"] for entry in logs] == [events.DB_CONNECTED]


def test_writer_survives_terminated_connection(
    fresh_database: str, writer_connection: psycopg.Connection[TupleRow]
) -> None:
    store = PostgresRecordStore(writer_connection, lambda: connect_as(fresh_database, WRITER_ROLE))
    in_queue: queue.Queue[MeterRecord] = queue.Queue()
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
    in_queue.put(MeterRecord(1, BASE_NS + 1_000_000_000, 120))
    captured: list[MutableMapping[str, Any]]
    with capture_logs() as captured:
        writer.step()

    with psycopg.connect(fresh_database) as reader:
        assert rows(reader, "SELECT value_kg FROM dms.meter_reading ORDER BY t") == [(100,), (120,)]
    assert [entry["event"] for entry in captured] == [
        events.DB_WRITE_ERROR,
        events.DB_WRITE_RECOVERED,
    ]
