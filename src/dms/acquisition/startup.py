import importlib.metadata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import psycopg
import structlog
from psycopg.rows import TupleRow

from dms.config.models import AcquisitionConfig
from dms.domain.rate_history import DEFAULT_RATE_HISTORY_CAPACITY, RateSample
from dms.logs import events
from dms.persistence.catalog import (
    close_crashed_events,
    start_run,
    sync_silos,
    sync_tanks,
    sync_temperature_sensors,
    tank_identity_violations,
    temperature_sensor_identity_violations,
)
from dms.persistence.rate_history import load_rate_samples
from dms.persistence.schema import (
    MigrationFilesError,
    SchemaIncompatibleError,
    SchemaVersionFormatError,
    check_schema_compatible,
)

PACKAGE_NAME = "dms"

logger = structlog.get_logger()


class StartupError(Exception):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class StartedRun:
    run_id: int
    rate_samples: dict[int, list[RateSample]]


def run_startup_sequence(
    connection: psycopg.Connection[TupleRow], config: AcquisitionConfig
) -> StartedRun:
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
            _refuse_identity_violations(connection, config)
            silos = sync_silos(connection, config.silos)
            tanks = sync_tanks(connection, config.tanks)
            temperature_sensors = sync_temperature_sensors(connection, config.temperature_sensors)
            run_id = start_run(
                connection,
                importlib.metadata.version(PACKAGE_NAME),
                config.model_dump(mode="json", exclude_none=True),
            )
            crashed_events = close_crashed_events(connection, run_id)
            rate_samples = _load_rate_history(connection, config)
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
        temperature_sensors_added=list(temperature_sensors.added),
        temperature_sensors_reactivated=list(temperature_sensors.reactivated),
        temperature_sensors_deactivated=list(temperature_sensors.deactivated),
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
    _log_rate_history(rate_samples, DEFAULT_RATE_HISTORY_CAPACITY)
    return StartedRun(run_id=run_id, rate_samples=rate_samples)


def _load_rate_history(
    connection: psycopg.Connection[TupleRow], config: AcquisitionConfig
) -> dict[int, list[RateSample]]:
    try:
        return load_rate_samples(
            connection, [tank.id for tank in config.tanks], DEFAULT_RATE_HISTORY_CAPACITY
        )
    except psycopg.Error as error:
        logger.critical(events.DB_STARTUP_FAILED, step="rate_history", error=str(error))
        raise StartupError(str(error)) from error


def _log_rate_history(rate_samples: Mapping[int, Sequence[RateSample]], capacity: int) -> None:
    logger.info(
        events.RATE_HISTORY_LOADED,
        tanks=[
            {"tank_id": tank_id, "samples": len(samples)}
            for tank_id, samples in rate_samples.items()
        ],
        capacity=capacity,
    )
    short = [tank_id for tank_id, samples in rate_samples.items() if len(samples) < capacity]
    if short:
        logger.warning(events.RATE_HISTORY_SHORT, tank_ids=short, capacity=capacity)


def _refuse_identity_violations(
    connection: psycopg.Connection[TupleRow], config: AcquisitionConfig
) -> None:
    moved_tanks = tank_identity_violations(connection, config.tanks)
    moved_sensors = temperature_sensor_identity_violations(connection, config.temperature_sensors)
    if not moved_tanks and not moved_sensors:
        return

    logger.critical(
        events.CATALOG_IDENTITY_VIOLATION,
        tanks=[
            {
                "tank_id": move.tank_id,
                "database_silo_id": move.database_silo_id,
                "config_silo_id": move.config_silo_id,
            }
            for move in moved_tanks
        ],
        temperature_sensors=[
            {
                "sensor_id": move.sensor_id,
                "database_silo_id": move.database_silo_id,
                "database_leg": move.database_leg,
                "config_silo_id": move.config_silo_id,
                "config_leg": move.config_leg,
            }
            for move in moved_sensors
        ],
    )
    raise StartupError(
        "catalog identity violated: "
        + ", ".join(
            [f"tank {move.tank_id}" for move in moved_tanks]
            + [f"temperature sensor {move.sensor_id}" for move in moved_sensors]
        )
    )
