from typing import cast

import psycopg
import pytest
from psycopg.rows import TupleRow
from structlog.testing import capture_logs

from dms.acquisition import startup
from dms.config.models import AcquisitionConfig
from dms.logs import events
from dms.persistence.connection import StartupError
from dms.persistence.schema import MigrationFilesError


def test_broken_migration_files_refuse_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_files(_connection: object) -> None:
        raise MigrationFilesError("0001_init.sql: not valid UTF-8")

    monkeypatch.setattr(startup, "check_schema_compatible", broken_files)
    unused_connection = cast(psycopg.Connection[TupleRow], object())

    with capture_logs() as logs, pytest.raises(StartupError, match="not valid UTF-8"):
        startup.run_startup_sequence(unused_connection, AcquisitionConfig(meters=(), silos=()))

    assert [(entry["event"], entry["step"]) for entry in logs] == [
        (events.DB_STARTUP_FAILED, "check_schema")
    ]
