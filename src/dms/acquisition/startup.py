import importlib.metadata

import psycopg
import structlog
from psycopg.rows import TupleRow

from dms.config.models import AcquisitionConfig
from dms.logs import events
from dms.persistence.catalog import start_run, sync_silos
from dms.persistence.connection import StartupError
from dms.persistence.schema import SchemaIncompatibleError, check_schema_compatible

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
    except psycopg.Error as error:
        logger.critical(events.DB_STARTUP_FAILED, step="check_schema", error=str(error))
        raise StartupError(str(error)) from error
    try:
        with connection.transaction():
            sync_silos(connection, config.silos)
            return start_run(
                connection,
                importlib.metadata.version(PACKAGE_NAME),
                config.model_dump(mode="json"),
            )
    except psycopg.Error as error:
        logger.critical(events.DB_STARTUP_FAILED, step="start_run", error=str(error))
        raise StartupError(str(error)) from error
