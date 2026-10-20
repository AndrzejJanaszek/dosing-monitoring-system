from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

import psycopg
from psycopg.rows import TupleRow
from psycopg.types.json import Jsonb

from dms.config.models import SiloConfig, TankConfig


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


def start_run(
    connection: psycopg.Connection[TupleRow], app_version: str, config: dict[str, Any]
) -> int:
    row = connection.execute(
        "INSERT INTO dms.run (started_at, app_version, config) VALUES (now(), %s, %s) RETURNING id",
        [app_version, Jsonb(config)],
    ).fetchone()
    if row is None:
        raise RuntimeError("INSERT INTO dms.run returned no row")
    run_id: int = row[0]
    return run_id


def close_crashed_events(
    connection: psycopg.Connection[TupleRow], current_run_id: int
) -> list[CrashClosedEvent]:
    rows = connection.execute(CLOSE_CRASHED_EVENTS_SQL, [current_run_id]).fetchall()
    return [CrashClosedEvent(event_id, tank_id) for event_id, tank_id in rows]


def stop_run(connection: psycopg.Connection[TupleRow], run_id: int) -> None:
    connection.execute("UPDATE dms.run SET stopped_at = now() WHERE id = %s", [run_id])


def sync_silos(
    connection: psycopg.Connection[TupleRow], silos: Sequence[SiloConfig]
) -> SyncResult:
    return _sync_catalog(
        connection,
        table="silo",
        upsert="INSERT INTO dms.silo (id, name, active) VALUES (%s, %s, true)"
        " ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, active = true",
        rows=[(silo.id, silo.name) for silo in silos],
    )


def sync_tanks(
    connection: psycopg.Connection[TupleRow], tanks: Sequence[TankConfig]
) -> SyncResult:
    return _sync_catalog(
        connection,
        table="tank",
        upsert="INSERT INTO dms.tank (id, name, silo_id, active) VALUES (%s, %s, %s, true)"
        " ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, active = true",
        rows=[(tank.id, tank.name, tank.silo_id) for tank in tanks],
    )


def tank_identity_violations(
    connection: psycopg.Connection[TupleRow], tanks: Sequence[TankConfig]
) -> list[TankMove]:
    config_silo_by_tank = {tank.id: tank.silo_id for tank in tanks}
    rows = connection.execute(
        "SELECT id, silo_id FROM dms.tank WHERE id = ANY(%s) ORDER BY id",
        [list(config_silo_by_tank)],
    ).fetchall()
    return [
        TankMove(tank_id, database_silo_id, config_silo_by_tank[tank_id])
        for tank_id, database_silo_id in rows
        if database_silo_id != config_silo_by_tank[tank_id]
    ]


def _sync_catalog(
    connection: psycopg.Connection[TupleRow],
    *,
    table: Literal["silo", "tank"],
    upsert: str,
    rows: list[tuple[Any, ...]],
) -> SyncResult:
    ids = [row[0] for row in rows]
    known: dict[int, bool] = {
        id_: active for id_, active in connection.execute(f"SELECT id, active FROM dms.{table}")
    }
    with connection.cursor() as cursor:
        cursor.executemany(upsert, rows)
    deactivated = connection.execute(
        f"UPDATE dms.{table} SET active = false WHERE active AND id <> ALL(%s) RETURNING id",
        [ids],
    ).fetchall()
    return SyncResult(
        added=tuple(sorted(id_ for id_ in ids if id_ not in known)),
        reactivated=tuple(sorted(id_ for id_ in ids if known.get(id_) is False)),
        deactivated=tuple(sorted(row[0] for row in deactivated)),
    )
