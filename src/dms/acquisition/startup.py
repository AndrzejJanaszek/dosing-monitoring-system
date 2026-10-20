import importlib.metadata

import psycopg
import structlog
from psycopg.rows import TupleRow

from dms.config.models import AcquisitionConfig
from dms.logs import events
from dms.persistence.catalog import (
    close_crashed_events,
    start_run,
    sync_silos,
    sync_tanks,
    tank_identity_violations,
)
from dms.persistence.connection import StartupError
from dms.persistence.schema import (
    MigrationFilesError,
    SchemaIncompatibleError,
    SchemaVersionFormatError,
    check_schema_compatible,
)

PACKAGE_NAME = "dms"


def run_startup_sequence(
    connection: psycopg.Connection[TupleRow], config: AcquisitionConfig
) -> int:
    logger = structlog.get_logger()
    try:
        check_schema_compatible(connection)
    except SchemaIncompatibleError as error:
        logger.critical(
            events.DB_SCHEMA_INCOMPATIBLE,
            database_version=str(error.database_version),
            package_version=str(error.package_version),
        )
        raise StartupError(str(error)) from error
    except (psycopg.Error, MigrationFilesError, SchemaVersionFormatError) as error:
        logger.critical(events.DB_STARTUP_FAILED, step="check_schema", error=str(error))
        raise StartupError(str(error)) from error
    try:
        with connection.transaction():
            _refuse_moved_tanks(connection, config)
            silos = sync_silos(connection, config.silos)
            tanks = sync_tanks(connection, config.tanks)
            run_id = start_run(
                connection,
                importlib.metadata.version(PACKAGE_NAME),
                config.model_dump(mode="json", exclude_none=True),
            )
            crashed_events = close_crashed_events(connection, run_id)
    except psycopg.Error as error:
        logger.critical(events.DB_STARTUP_FAILED, step="catalog_and_run", error=str(error))
        raise StartupError(str(error)) from error
    logger.info(
        events.CATALOG_SYNCED,
        silos_added=list(silos.added),
        silos_reactivated=list(silos.reactivated),
        silos_deactivated=list(silos.deactivated),
        tanks_added=list(tanks.added),
        tanks_reactivated=list(tanks.reactivated),
        tanks_deactivated=list(tanks.deactivated),
    )

    if crashed_events:
        logger.error(
            events.EVENT_CRASH_CLOSED,
            count=len(crashed_events),
            events=[
                {"event_id": str(item.event_id), "tank_id": item.tank_id}
                for item in crashed_events
            ],
        )
    return run_id


def _refuse_moved_tanks(
    connection: psycopg.Connection[TupleRow], config: AcquisitionConfig
) -> None:
    violations = tank_identity_violations(connection, config.tanks)
    if not violations:
        return
    structlog.get_logger().critical(
        events.CATALOG_IDENTITY_VIOLATION,
        tanks=[
            {
                "tank_id": move.tank_id,
                "database_silo_id": move.database_silo_id,
                "config_silo_id": move.config_silo_id,
            }
            for move in violations
        ],
    )
    raise StartupError(
        "tanks moved to a different silo: " + ", ".join(str(m.tank_id) for m in violations)
    )
