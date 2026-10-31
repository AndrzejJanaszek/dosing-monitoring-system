from collections.abc import Sequence

import psycopg
from psycopg.rows import TupleRow

from dms.domain.rate_history import RateSample
from dms.units import NS_PER_MS

LOAD_RATE_SAMPLES_SQL = (
    "SELECT tank_id, id, start_value_kg - end_value_kg, duration_ms FROM ("
    " SELECT tank_id, id, start_value_kg, end_value_kg, duration_ms, start_at,"
    " row_number() OVER (PARTITION BY tank_id ORDER BY start_at DESC, id DESC) AS position"
    " FROM dms.tank_event"
    " WHERE type = 'dispense' AND status = 'completed'"
    " AND collision = false AND rule_violation = false"
    " AND start_value_kg > end_value_kg AND duration_ms > 0"
    " AND tank_id = ANY(%s)"
    ") AS recent"
    " WHERE position <= %s"
    " ORDER BY tank_id, start_at, id"
)


def load_rate_samples(
    connection: psycopg.Connection[TupleRow], tank_ids: Sequence[int], capacity: int
) -> dict[int, list[RateSample]]:
    samples: dict[int, list[RateSample]] = {tank_id: [] for tank_id in tank_ids}
    rows = connection.execute(LOAD_RATE_SAMPLES_SQL, [list(tank_ids), capacity]).fetchall()
    for tank_id, event_id, mass_kg, duration_ms in rows:
        samples[tank_id].append(
            RateSample(event_id=event_id, mass_kg=mass_kg, duration_ns=duration_ms * NS_PER_MS)
        )
    return samples
