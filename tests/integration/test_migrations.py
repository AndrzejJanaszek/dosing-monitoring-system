from pathlib import Path

import psycopg
import pytest
from psycopg import errors
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import TupleRow

from dms.persistence.migrate import (
    ChecksumMismatchError,
    DatabaseAheadError,
    apply_migrations,
    main,
)
from dms.persistence.schema import (
    SchemaIncompatibleError,
    SchemaVersion,
    check_schema_compatible,
    database_schema_version,
    load_migrations,
    package_schema_version,
)
from tests.database import migrate_as_owner, set_role


def owner_connection(database_url: str) -> psycopg.Connection[TupleRow]:
    connection = psycopg.connect(database_url, autocommit=True)
    connection.execute("SET ROLE dms_owner")
    return connection


def table_names(connection: psycopg.Connection[TupleRow]) -> set[str]:
    rows = connection.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'dms'"
    ).fetchall()
    return {row[0] for row in rows}


def test_migration_on_empty_database_creates_tables_and_records_versions(
    fresh_database: str,
) -> None:
    with owner_connection(fresh_database) as connection:
        applied = apply_migrations(connection, load_migrations())

        assert [migration.version for migration in applied] == [1, 2, 3, 4, 5]
        assert table_names(connection) == {
            "schema_migration",
            "silo",
            "tank",
            "tank_event",
            "temperature_sensor",
            "run",
            "meter_reading",
        }
        assert database_schema_version(connection) == package_schema_version()
        assert str(package_schema_version()) == "1.4.0"


def test_second_run_changes_nothing(fresh_database: str) -> None:
    with owner_connection(fresh_database) as connection:
        apply_migrations(connection, load_migrations())

        assert apply_migrations(connection, load_migrations()) == []
        row = connection.execute("SELECT count(*) FROM dms.schema_migration").fetchone()
        assert row == (5,)


def test_changed_checksum_is_refused_and_database_untouched(fresh_database: str) -> None:
    with owner_connection(fresh_database) as connection:
        apply_migrations(connection, load_migrations())
        connection.execute("UPDATE dms.schema_migration SET checksum = 'tampered'")
        connection.execute("DROP TABLE dms.meter_reading")

        with pytest.raises(ChecksumMismatchError) as raised:
            apply_migrations(connection, load_migrations())

        assert raised.value.files == [
            "0001_init.sql",
            "0002_tank.sql",
            "0003_tank_event.sql",
            "0004_event_recovery.sql",
            "0005_temperature_sensor.sql",
        ]
        assert "meter_reading" not in table_names(connection)


def test_database_ahead_of_package_is_refused(fresh_database: str) -> None:
    with owner_connection(fresh_database) as connection:
        apply_migrations(connection, load_migrations())
        connection.execute(
            "INSERT INTO dms.schema_migration VALUES (6, 'future', 'x', '1.5.0', now())"
        )

        with pytest.raises(DatabaseAheadError) as raised:
            apply_migrations(connection, load_migrations())

        assert raised.value.migrations == ["0006_future"]


def test_failing_migration_leaves_no_trace(fresh_database: str, tmp_path: Path) -> None:
    (tmp_path / "0001_init.sql").write_text(
        "-- schema-change: major\nCREATE TABLE dms.half (id integer);\nSELECT 1 / 0;\n",
        encoding="utf-8",
    )
    with owner_connection(fresh_database) as connection:
        with pytest.raises(errors.DivisionByZero):
            apply_migrations(connection, load_migrations(tmp_path))

        assert "half" not in table_names(connection)
        row = connection.execute("SELECT count(*) FROM dms.schema_migration").fetchone()
        assert row == (0,)


def test_schema_check_fails_without_migration_table(fresh_database: str) -> None:
    with psycopg.connect(fresh_database) as connection:
        with pytest.raises(SchemaIncompatibleError) as raised:
            check_schema_compatible(connection)

        assert raised.value.database_version is None


def test_schema_check_passes_after_migration(fresh_database: str) -> None:
    migrate_as_owner(fresh_database)

    with psycopg.connect(fresh_database) as connection:
        assert check_schema_compatible(connection) == package_schema_version()


def test_schema_check_fails_for_other_major(fresh_database: str) -> None:
    migrate_as_owner(fresh_database)
    with owner_connection(fresh_database) as connection:
        connection.execute("UPDATE dms.schema_migration SET schema_version = '2.0.0'")

    with psycopg.connect(fresh_database) as connection:
        with pytest.raises(SchemaIncompatibleError) as raised:
            check_schema_compatible(connection)

        assert raised.value.database_version == SchemaVersion(2, 0, 0)


def test_api_role_cannot_insert_meter_reading(
    migrated_connection: psycopg.Connection[TupleRow],
) -> None:
    migrated_connection.execute("INSERT INTO dms.silo VALUES (1, 'Silos 1', true)")
    set_role(migrated_connection, "dms_api")

    with pytest.raises(errors.InsufficientPrivilege):
        migrated_connection.execute(
            "INSERT INTO dms.meter_reading (silo_id, t, value_kg) VALUES (1, now(), 10)"
        )


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO dms.tank_event (id, tank_id, run_id, type, origin, status, start_at,"
        " start_quality) VALUES (gen_random_uuid(), 1, 1, 'dispense', 'signal', 'in_progress',"
        " now(), 'unknown')",
        "UPDATE dms.tank_event SET status = 'completed'",
    ],
)
@pytest.mark.parametrize("role", ["dms_api", "dms_read"])
def test_read_roles_cannot_write_tank_event(
    migrated_connection: psycopg.Connection[TupleRow], role: str, statement: str
) -> None:
    set_role(migrated_connection, role)

    with pytest.raises(errors.InsufficientPrivilege):
        migrated_connection.execute(statement)


def test_writer_role_inserts_meter_reading(
    migrated_connection: psycopg.Connection[TupleRow],
) -> None:
    set_role(migrated_connection, "dms_writer")
    migrated_connection.execute("INSERT INTO dms.silo VALUES (1, 'Silos 1', true)")

    migrated_connection.execute(
        "INSERT INTO dms.meter_reading (silo_id, t, value_kg) VALUES (1, now(), 10)"
    )


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM dms.silo",
        "DELETE FROM dms.meter_reading",
        "DELETE FROM dms.tank_event",
        "UPDATE dms.meter_reading SET value_kg = 0",
        "CREATE TABLE dms.probe (id integer)",
        "DROP TABLE dms.silo",
        "INSERT INTO dms.schema_migration VALUES (9, 'x', 'x', '1.0.0', now())",
    ],
)
def test_writer_role_is_refused_forbidden_statements(
    migrated_connection: psycopg.Connection[TupleRow], statement: str
) -> None:
    set_role(migrated_connection, "dms_writer")

    with pytest.raises((errors.InsufficientPrivilege, errors.UndefinedTable)):
        migrated_connection.execute(statement)


@pytest.mark.parametrize(
    "table",
    [
        "silo",
        "tank",
        "run",
        "meter_reading",
        "tank_event",
        "temperature_sensor",
        "schema_migration",
    ],
)
@pytest.mark.parametrize("role", ["dms_api", "dms_read"])
def test_read_roles_read_tables(
    migrated_connection: psycopg.Connection[TupleRow], role: str, table: str
) -> None:
    set_role(migrated_connection, role)

    migrated_connection.execute(f"SELECT * FROM dms.{table}")


@pytest.mark.parametrize(
    "table", ["silo", "run", "schema_migration", "meter_reading", "temperature_sensor"]
)
def test_writer_role_reads_tables_it_needs(
    migrated_connection: psycopg.Connection[TupleRow], table: str
) -> None:
    set_role(migrated_connection, "dms_writer")

    migrated_connection.execute(f"SELECT * FROM dms.{table}")


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO dms.temperature_sensor VALUES (1, NULL, 1, 'Czujnik', true)",
        "INSERT INTO dms.temperature_sensor VALUES (1, 1, 0, 'Czujnik', true)",
    ],
    ids=["leg-without-silo", "leg-below-one"],
)
def test_temperature_sensor_leg_is_checked(
    migrated_connection: psycopg.Connection[TupleRow], statement: str
) -> None:
    migrated_connection.execute("INSERT INTO dms.silo VALUES (1, 'Silos 1', true)")

    with pytest.raises(errors.CheckViolation):
        migrated_connection.execute(statement)


def test_command_applies_migrations_with_owner_role(
    fresh_database: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    parameters = conninfo_to_dict(fresh_database)
    with psycopg.connect(fresh_database, autocommit=True) as superuser:
        superuser.execute("ALTER ROLE dms_owner PASSWORD 'dms'")
    (tmp_path / "shared.toml").write_text(
        f'[database]\nhost = "{parameters["host"]}"\nport = {parameters["port"]}\n'
        f'dbname = "{parameters["dbname"]}"\n[logging]\nformat = "json"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("DMS_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("PGPASSWORD", "dms")

    assert main() == 0

    with psycopg.connect(fresh_database) as connection:
        assert database_schema_version(connection) == package_schema_version()
