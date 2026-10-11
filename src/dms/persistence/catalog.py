from collections.abc import Sequence
from typing import Any

import psycopg
from psycopg.rows import TupleRow
from psycopg.types.json import Jsonb

from dms.config.models import SiloConfig


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


def stop_run(connection: psycopg.Connection[TupleRow], run_id: int) -> None:
    connection.execute("UPDATE dms.run SET stopped_at = now() WHERE id = %s", [run_id])


def sync_silos(connection: psycopg.Connection[TupleRow], silos: Sequence[SiloConfig]) -> None:
    with connection.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO dms.silo (id, name, active) VALUES (%s, %s, true)"
            " ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, active = true",
            [(silo.id, silo.name) for silo in silos],
        )
    connection.execute(
        "UPDATE dms.silo SET active = false WHERE active AND id <> ALL(%s)",
        [[silo.id for silo in silos]],
    )
