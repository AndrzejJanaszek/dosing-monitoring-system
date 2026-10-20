from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.rows import TupleRow
from psycopg.types.json import Jsonb

from dms.config.models import SiloConfig, TankConfig

CLOSE_CRASHED_EVENTS_SQL = """
UPDATE dms.tank_event AS event
SET status = 'incomplete',
    end_quality = 'service_crashed',
    end_at = coalesce(
        (
            SELECT max(reading.t)
            FROM dms.meter_reading AS reading
            WHERE reading.silo_id = tank.silo_id
              AND reading.t >= event.start_at
              AND reading.t < (
                  SELECT min(next_run.started_at)
                  FROM dms.run AS next_run
                  WHERE next_run.started_at > event_run.started_at
              )
        ),
        event.start_at
    )
FROM dms.tank AS tank, dms.run AS event_run
WHERE tank.id = event.tank_id
  AND event_run.id = event.run_id
  AND event.status = 'in_progress'
  AND event.run_id <> %s
RETURNING event.id, event.tank_id
"""


START_RUN_SQL = (
    "INSERT INTO dms.run (started_at, app_version, config) VALUES (now(), %s, %s) RETURNING id"
)

STOP_RUN_SQL = "UPDATE dms.run SET stopped_at = now() WHERE id = %s"

UPSERT_SILO_SQL = (
    "INSERT INTO dms.silo (id, name, active) VALUES (%s, %s, true)"
    " ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, active = true"
)

UPSERT_TANK_SQL = (
    "INSERT INTO dms.tank (id, name, silo_id, active) VALUES (%s, %s, %s, true)"
    " ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, active = true"
)

SELECT_TANK_SILOS_SQL = "SELECT id, silo_id FROM dms.tank WHERE id = ANY(%s) ORDER BY id"

SELECT_CATALOG_ACTIVITY_SQL = "SELECT id, active FROM {table}"

DEACTIVATE_MISSING_SQL = (
    "UPDATE {table} SET active = false WHERE active AND id <> ALL(%s) RETURNING id"
)


class RunNotStartedError(Exception):
    pass


class _CatalogTable(StrEnum):
    SILO = "silo"
    TANK = "tank"


@dataclass(frozen=True, slots=True)
class SyncResult:
    added: tuple[int, ...]
    reactivated: tuple[int, ...]
    deactivated: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class TankMove:
    tank_id: int
    database_silo_id: int
    config_silo_id: int


@dataclass(frozen=True, slots=True)
class CrashClosedEvent:
    event_id: UUID
    tank_id: int


def start_run(
    connection: psycopg.Connection[TupleRow], app_version: str, config: dict[str, Any]
) -> int:
    row = connection.execute(START_RUN_SQL, [app_version, Jsonb(config)]).fetchone()
    if row is None:
        raise RunNotStartedError("INSERT INTO dms.run returned no row")
    run_id: int = row[0]
    return run_id


def close_crashed_events(
    connection: psycopg.Connection[TupleRow], current_run_id: int
) -> list[CrashClosedEvent]:
    rows = connection.execute(CLOSE_CRASHED_EVENTS_SQL, [current_run_id]).fetchall()
    return [CrashClosedEvent(event_id, tank_id) for event_id, tank_id in rows]


def stop_run(connection: psycopg.Connection[TupleRow], run_id: int) -> None:
    connection.execute(STOP_RUN_SQL, [run_id])


def sync_silos(
    connection: psycopg.Connection[TupleRow], silos: Sequence[SiloConfig]
) -> SyncResult:
    return _sync_catalog(
        connection,
        table=_CatalogTable.SILO,
        upsert_sql=UPSERT_SILO_SQL,
        rows=[(silo.id, silo.name) for silo in silos],
    )


def sync_tanks(
    connection: psycopg.Connection[TupleRow], tanks: Sequence[TankConfig]
) -> SyncResult:
    return _sync_catalog(
        connection,
        table=_CatalogTable.TANK,
        upsert_sql=UPSERT_TANK_SQL,
        rows=[(tank.id, tank.name, tank.silo_id) for tank in tanks],
    )


def tank_identity_violations(
    connection: psycopg.Connection[TupleRow], tanks: Sequence[TankConfig]
) -> list[TankMove]:
    config_silo_by_tank = {tank.id: tank.silo_id for tank in tanks}
    rows = connection.execute(SELECT_TANK_SILOS_SQL, [list(config_silo_by_tank)]).fetchall()
    return [
        TankMove(tank_id, database_silo_id, config_silo_by_tank[tank_id])
        for tank_id, database_silo_id in rows
        if database_silo_id != config_silo_by_tank[tank_id]
    ]


def _sync_catalog(
    connection: psycopg.Connection[TupleRow],
    *,
    table: _CatalogTable,
    upsert_sql: str,
    rows: list[tuple[Any, ...]],
) -> SyncResult:
    table_name = sql.Identifier("dms", table)
    catalog_ids = [row[0] for row in rows]
    known: dict[int, bool] = {
        catalog_id: active
        for catalog_id, active in connection.execute(
            sql.SQL(SELECT_CATALOG_ACTIVITY_SQL).format(table=table_name)
        )
    }

    with connection.cursor() as cursor:
        cursor.executemany(upsert_sql, rows)
    deactivated = connection.execute(
        sql.SQL(DEACTIVATE_MISSING_SQL).format(table=table_name), [catalog_ids]
    ).fetchall()

    return SyncResult(
        added=tuple(sorted(item for item in catalog_ids if item not in known)),
        reactivated=tuple(sorted(item for item in catalog_ids if known.get(item) is False)),
        deactivated=tuple(sorted(row[0] for row in deactivated)),
    )
