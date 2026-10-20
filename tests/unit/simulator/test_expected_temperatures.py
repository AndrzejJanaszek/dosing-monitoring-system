from decimal import Decimal

import pytest

from dms.domain.temperature_error import TemperatureError
from dms.simulator.expected_temperatures import (
    ExpectedTemperatureRow,
    TemperatureExpectations,
    expected_temperature_rows,
)
from dms.simulator.layout import (
    ErrorCode,
    FixedValue,
    Missing,
    PlantLayout,
    SensorFault,
    SignalBoard,
    SiloLayout,
    TemperatureSensor,
)
from dms.simulator.timeline import scenario_samples
from dms.units import NS_PER_S
from tests.unit.simulator.builders import scenario_with, tank

ADDRESS = "28A8F126AB240B1C"
OTHER_ADDRESS = "28FF4A7C61160398"
DURATION_S = 20


def expectations(
    record_interval_s: float = 1.0, max_reading_age_s: float = 5.0
) -> TemperatureExpectations:
    return TemperatureExpectations(
        tick_interval_ns=NS_PER_S,
        record_interval_ns=round(record_interval_s * NS_PER_S),
        max_reading_age_ns=round(max_reading_age_s * NS_PER_S),
        min_valid_c=-40.0,
        max_valid_c=80.0,
    )


def sensor(
    sensor_id: int = 1,
    address: str = ADDRESS,
    *,
    faults: tuple[SensorFault, ...] = (),
    configured: bool = True,
    rate_c_per_min: float = 0.0,
) -> TemperatureSensor:
    return TemperatureSensor(
        id=sensor_id,
        address=address,
        start_c=21.5,
        rate_c_per_min=rate_c_per_min,
        faults=faults,
        configured=configured,
    )


def rows_for(
    *sensors: TemperatureSensor,
    settings: TemperatureExpectations | None = None,
    period_s: float = 1.0,
) -> list[ExpectedTemperatureRow]:
    layout = PlantLayout(
        (SiloLayout(id=1, tanks=(tank(1, 4, 5),)),),
        SignalBoard(sensors=sensors, temperatures_period_s=period_s),
    )
    samples = list(scenario_samples(scenario_with(layout=layout, duration_s=DURATION_S)))
    ticks = list(range(0, DURATION_S * NS_PER_S + 1, NS_PER_S))
    return expected_temperature_rows(
        layout, samples, tick_times_ns=ticks, expectations=settings or expectations()
    )


def fault(start_s: float, end_s: float, kind: ErrorCode | FixedValue | Missing) -> SensorFault:
    return SensorFault(start_s=start_s, end_s=end_s, kind=kind)


def test_a_sample_on_the_tick_is_seen_only_by_the_next_tick() -> None:
    rows = rows_for(sensor())

    assert [row.wall_ns // NS_PER_S for row in rows][:3] == [0, 1, 2]
    assert len(rows) == DURATION_S


def test_configured_sensor_has_an_id_and_unknown_address_has_none() -> None:
    rows = rows_for(sensor(), sensor(2, OTHER_ADDRESS, configured=False))

    assert {(row.address, row.sensor_id) for row in rows} == {(ADDRESS, 1), (OTHER_ADDRESS, None)}


def test_value_is_formatted_to_two_places() -> None:
    rows = rows_for(sensor(rate_c_per_min=1.0))

    assert [row.value_c for row in rows[:3]] == [
        Decimal("21.50"),
        Decimal("21.52"),
        Decimal("21.53"),
    ]


@pytest.mark.parametrize(
    ("code", "error"),
    [
        ("read_failed", TemperatureError.READ_FAILED),
        ("power_reset", TemperatureError.POWER_RESET),
        ("insufficient_power", TemperatureError.INSUFFICIENT_POWER),
        ("crc_error", TemperatureError.UNRECOGNIZED),
        ("out_of_range", TemperatureError.UNRECOGNIZED),
    ],
)
def test_error_codes_map_to_errors_without_a_value(code: str, error: TemperatureError) -> None:
    rows = rows_for(sensor(faults=(fault(5.0, 6.0, ErrorCode(code)),)))

    (failing,) = [row for row in rows if row.error is not None]
    assert (failing.value_c, failing.error) == (None, error)
    assert failing.wall_ns == 5 * NS_PER_S


@pytest.mark.parametrize("value_c", [-127.0, 85.0, 150.25])
def test_value_outside_the_range_keeps_the_value_as_out_of_range(value_c: float) -> None:
    rows = rows_for(sensor(faults=(fault(5.0, 6.0, FixedValue(value_c)),)))

    (failing,) = [row for row in rows if row.error is not None]
    assert (failing.value_c, failing.error) == (
        Decimal(f"{value_c:.2f}"),
        TemperatureError.OUT_OF_RANGE,
    )


def test_missing_reading_gives_no_row_for_that_second() -> None:
    rows = rows_for(sensor(faults=(fault(5.0, 6.0, Missing()),)))

    assert 5 * NS_PER_S not in [row.wall_ns for row in rows]
    assert len(rows) == DURATION_S - 1


def test_reading_as_old_as_the_limit_is_still_recorded() -> None:
    rows = rows_for(sensor(faults=(fault(5.0, 11.0, Missing()),)), period_s=1.0)

    recorded_ns = [row.wall_ns for row in rows]
    assert 4 * NS_PER_S in recorded_ns
    assert not any(5 * NS_PER_S <= ns <= 10 * NS_PER_S for ns in recorded_ns)
    assert 11 * NS_PER_S in recorded_ns


def test_record_interval_longer_than_the_tick_thins_the_rows() -> None:
    rows = rows_for(sensor(), settings=expectations(record_interval_s=5.0))

    assert [row.wall_ns // NS_PER_S for row in rows] == [0, 5, 10, 15]


def test_reading_slower_than_the_tick_is_recorded_once() -> None:
    rows = rows_for(sensor(), period_s=2.0)

    assert [row.wall_ns // NS_PER_S for row in rows] == [0, 2, 4, 6, 8, 10, 12, 14, 16, 18]


def test_unknown_address_forgotten_after_a_silence_is_recorded_without_waiting() -> None:
    silent = fault(3.0, 12.0, Missing())
    rows = rows_for(
        sensor(2, OTHER_ADDRESS, configured=False, faults=(silent,)),
        settings=expectations(record_interval_s=8.0),
    )

    assert [row.wall_ns // NS_PER_S for row in rows] == [0, 12]
