from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from dms.domain.temperature_error import TemperatureError
from dms.simulator.encoders import TEMPERATURE_FORMAT
from dms.simulator.layout import PlantLayout
from dms.simulator.timeline import Sample, SimulatedReading, TemperaturesSample

BOARD_ERRORS = {
    error.value: error
    for error in (
        TemperatureError.READ_FAILED,
        TemperatureError.POWER_RESET,
        TemperatureError.INSUFFICIENT_POWER,
    )
}


@dataclass(frozen=True, slots=True, kw_only=True)
class TemperatureExpectations:
    tick_interval_ns: int
    record_interval_ns: int
    max_reading_age_ns: int
    min_valid_c: float
    max_valid_c: float


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpectedTemperatureRow:
    sensor_id: int | None
    address: str
    wall_ns: int
    value_c: Decimal | None
    error: TemperatureError | None


def expected_temperature_rows(
    layout: PlantLayout,
    samples: Sequence[Sample],
    *,
    tick_times_ns: Sequence[int],
    expectations: TemperatureExpectations,
) -> list[ExpectedTemperatureRow]:
    sensor_id_by_address = {
        sensor.address: sensor.id for sensor in layout.board.sensors if sensor.configured
    }
    readings_by_address: dict[str, list[tuple[int, SimulatedReading]]] = {}
    for sample in samples:
        if isinstance(sample, TemperaturesSample):
            for reading in sample.readings:
                readings_by_address.setdefault(reading.address, []).append((sample.at_ns, reading))

    rows: list[ExpectedTemperatureRow] = []
    for address, readings in readings_by_address.items():
        rows.extend(
            _rows_of(
                address,
                sensor_id_by_address.get(address),
                readings,
                tick_times_ns,
                expectations,
            )
        )
    return sorted(rows, key=lambda row: (row.wall_ns, row.address))


def _rows_of(
    address: str,
    sensor_id: int | None,
    readings: list[tuple[int, SimulatedReading]],
    tick_times_ns: Sequence[int],
    expectations: TemperatureExpectations,
) -> list[ExpectedTemperatureRow]:
    received_at_ns = [at_ns for at_ns, _ in readings]
    rows: list[ExpectedTemperatureRow] = []
    last_recorded_at_ns: int | None = None
    last_record_tick_ns: int | None = None
    tolerance_ns = expectations.tick_interval_ns // 2

    for tick_ns in tick_times_ns:
        seen = bisect_left(received_at_ns, tick_ns)
        if seen == 0:
            continue
        at_ns, reading = readings[seen - 1]

        if tick_ns - at_ns > expectations.max_reading_age_ns:
            if sensor_id is None:
                last_recorded_at_ns = None
                last_record_tick_ns = None
            continue
        if at_ns == last_recorded_at_ns:
            continue
        if (
            last_record_tick_ns is not None
            and tick_ns - last_record_tick_ns < expectations.record_interval_ns - tolerance_ns
        ):
            continue

        last_recorded_at_ns = at_ns
        last_record_tick_ns = tick_ns
        rows.append(_row_of(address, sensor_id, at_ns, reading, expectations))
    return rows


def _row_of(
    address: str,
    sensor_id: int | None,
    at_ns: int,
    reading: SimulatedReading,
    expectations: TemperatureExpectations,
) -> ExpectedTemperatureRow:
    value_c: Decimal | None = None
    error: TemperatureError | None = None
    if reading.error_code is not None:
        error = BOARD_ERRORS.get(reading.error_code, TemperatureError.UNRECOGNIZED)
    elif reading.value_c is not None:
        value_c = Decimal(f"{reading.value_c:{TEMPERATURE_FORMAT}}")
        if not expectations.min_valid_c <= float(value_c) <= expectations.max_valid_c:
            error = TemperatureError.OUT_OF_RANGE
    return ExpectedTemperatureRow(
        sensor_id=sensor_id, address=address, wall_ns=at_ns, value_c=value_c, error=error
    )
