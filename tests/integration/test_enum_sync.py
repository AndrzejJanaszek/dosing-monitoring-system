from enum import StrEnum

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import TupleRow

from dms.domain.events import EndQuality, EventKind, EventStatus, StartQuality
from dms.domain.temperature_error import TemperatureError
from dms.persistence.record_store import EventOrigin


@pytest.mark.parametrize(
    ("enum", "database_type"),
    [
        pytest.param(EventKind, "event_type", id="event-kind"),
        pytest.param(EventOrigin, "event_origin", id="event-origin"),
        pytest.param(EventStatus, "event_status", id="event-status"),
        pytest.param(StartQuality, "start_quality", id="start-quality"),
        pytest.param(EndQuality, "end_quality", id="end-quality"),
        pytest.param(TemperatureError, "temperature_error", id="temperature-error"),
    ],
)
def test_string_enum_has_the_values_of_the_database_enum(
    migrated_connection: psycopg.Connection[TupleRow], enum: type[StrEnum], database_type: str
) -> None:
    rows = migrated_connection.execute(
        sql.SQL("SELECT unnest(enum_range(NULL::{type}))::text").format(
            type=sql.Identifier("dms", database_type)
        )
    ).fetchall()

    assert {value for (value,) in rows} == {member.value for member in enum}
