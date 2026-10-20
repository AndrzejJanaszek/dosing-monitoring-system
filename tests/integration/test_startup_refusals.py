from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

import psycopg
import pytest

from dms.acquisition import startup
from dms.acquisition.startup import StartupError
from dms.config.models import AcquisitionConfig
from dms.logs import events
from dms.persistence import schema

MALFORMED_SCHEMA_VERSION = "0.0.0.1"


def test_broken_migration_files_refuse_startup(
    monkeypatch: pytest.MonkeyPatch,
    fresh_database: str,
    tmp_path: Path,
    logs: list[MutableMapping[str, Any]],
) -> None:
    (tmp_path / "0001_init.sql").write_bytes(b"\xff\xfe")
    monkeypatch.setattr(schema, "packaged_migrations_directory", lambda: tmp_path)

    with (
        psycopg.connect(fresh_database, autocommit=True) as connection,
        pytest.raises(StartupError, match="not valid UTF-8"),
    ):
        startup.run_startup_sequence(connection, AcquisitionConfig(meters=(), silos=()))

    assert [(entry["event"], entry["step"]) for entry in logs] == [
        (events.DB_STARTUP_FAILED, "check_schema")
    ]


def test_malformed_database_schema_version_refuses_startup(
    fresh_database: str, logs: list[MutableMapping[str, Any]]
) -> None:
    with psycopg.connect(fresh_database, autocommit=True) as connection:
        connection.execute(
            "CREATE TABLE dms.schema_migration (version integer, schema_version text)"
        )
        connection.execute(
            "INSERT INTO dms.schema_migration VALUES (1, %s)", [MALFORMED_SCHEMA_VERSION]
        )

        with pytest.raises(StartupError, match=r"0\.0\.0\.1"):
            startup.run_startup_sequence(connection, AcquisitionConfig(meters=(), silos=()))

    assert [(entry["event"], entry["step"]) for entry in logs] == [
        (events.DB_STARTUP_FAILED, "check_schema")
    ]
