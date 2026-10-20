import pytest

from dms.domain.records import TemperatureRecord, UnknownSensorRecord
from dms.domain.temperature_error import TemperatureError
from dms.domain.temperatures import (
    SensorErrorEnded,
    SensorErrorStarted,
    SensorStale,
    SensorStaleEnded,
    TemperatureNotice,
    TemperatureSensors,
    UnknownSensorGone,
    UnknownSensorSeen,
)
from dms.messages import TemperatureReadings, Tick
from dms.units import NS_PER_S
from tests.unit.domain.builders import (
    OTHER_ADDRESS,
    SENSOR_ADDRESS,
    SENSOR_ID,
    WALL_OFFSET_NS,
    build_temperature_sensors,
    temperature_readings,
)


def reading_of(
    at_s: float, value_c: float | None, error_code: str | None = None
) -> TemperatureReadings:
    return temperature_readings(at_s, (SENSOR_ADDRESS, value_c, error_code))


def tick(at_s: float) -> Tick:
    return Tick(WALL_OFFSET_NS + round(at_s * NS_PER_S), round(at_s * NS_PER_S))


def record(
    at_s: float, value_c: float | None, error: TemperatureError | None = None
) -> TemperatureRecord:
    return TemperatureRecord(
        sensor_id=SENSOR_ID,
        wall_ns=WALL_OFFSET_NS + round(at_s * NS_PER_S),
        value_c=value_c,
        error=error,
    )


def feed(
    sensors: TemperatureSensors, at_s: float, value_c: float | None, code: str | None = None
) -> list[TemperatureNotice]:
    return sensors.on_readings(reading_of(at_s, value_c, code))


def test_fresh_reading_is_recorded_with_its_receipt_time_on_the_next_tick() -> None:
    sensors = build_temperature_sensors()
    feed(sensors, 0.4, 21.5)

    assert sensors.on_tick(tick(1.0)) == [record(0.4, 21.5)]


def test_tick_without_any_reading_records_nothing() -> None:
    sensors = build_temperature_sensors()

    assert sensors.on_tick(tick(1.0)) == []


def test_reading_is_recorded_only_once() -> None:
    sensors = build_temperature_sensors()
    feed(sensors, 0.4, 21.5)
    sensors.on_tick(tick(1.0))

    assert sensors.on_tick(tick(2.0)) == []


def test_only_the_latest_reading_between_ticks_is_recorded() -> None:
    sensors = build_temperature_sensors()
    feed(sensors, 0.2, 21.0)
    feed(sensors, 0.9, 22.0)

    assert sensors.on_tick(tick(1.0)) == [record(0.9, 22.0)]


@pytest.mark.parametrize(
    "error",
    [
        TemperatureError.READ_FAILED,
        TemperatureError.POWER_RESET,
        TemperatureError.INSUFFICIENT_POWER,
    ],
)
def test_error_reported_by_the_board_is_recorded_without_a_value(error: TemperatureError) -> None:
    sensors = build_temperature_sensors()
    feed(sensors, 0.5, None, error.value)

    assert sensors.on_tick(tick(1.0)) == [record(0.5, None, error)]


@pytest.mark.parametrize("code", ["crc_error", "out_of_range", "unrecognized", "READ_FAILED"])
def test_error_code_unknown_to_dms_is_recorded_as_unrecognized_and_reported_raw(
    code: str,
) -> None:
    sensors = build_temperature_sensors()

    notices = feed(sensors, 0.5, None, code)

    assert notices == [
        SensorErrorStarted(
            sensor_id=SENSOR_ID, error=TemperatureError.UNRECOGNIZED, error_code=code
        )
    ]
    assert sensors.on_tick(tick(1.0)) == [record(0.5, None, TemperatureError.UNRECOGNIZED)]


@pytest.mark.parametrize("value_c", [-127.0, 85.0, -40.01, 80.01, 150.25])
def test_value_outside_the_valid_range_is_recorded_as_out_of_range_with_the_value(
    value_c: float,
) -> None:
    sensors = build_temperature_sensors()
    feed(sensors, 0.5, value_c)

    assert sensors.on_tick(tick(1.0)) == [record(0.5, value_c, TemperatureError.OUT_OF_RANGE)]


@pytest.mark.parametrize("value_c", [-40.0, 0.0, 80.0])
def test_value_on_the_edge_of_the_valid_range_is_a_normal_reading(value_c: float) -> None:
    sensors = build_temperature_sensors()
    feed(sensors, 0.5, value_c)

    assert sensors.on_tick(tick(1.0)) == [record(0.5, value_c)]


def test_error_starts_once_and_ends_with_its_duration() -> None:
    sensors = build_temperature_sensors()

    first = feed(sensors, 1.0, None, "read_failed")
    repeated = feed(sensors, 2.0, None, "power_reset")
    ended = feed(sensors, 4.0, 21.0)
    ended_again = feed(sensors, 5.0, 21.0)

    assert first == [
        SensorErrorStarted(
            sensor_id=SENSOR_ID, error=TemperatureError.READ_FAILED, error_code=None
        )
    ]
    assert repeated == []
    assert ended == [SensorErrorEnded(sensor_id=SENSOR_ID, duration_ns=3 * NS_PER_S)]
    assert ended_again == []


def test_out_of_range_value_starts_an_error() -> None:
    sensors = build_temperature_sensors()

    notices = feed(sensors, 1.0, 85.0)

    assert notices == [
        SensorErrorStarted(
            sensor_id=SENSOR_ID, error=TemperatureError.OUT_OF_RANGE, error_code=None
        )
    ]


def test_reading_exactly_as_old_as_the_limit_is_still_fresh() -> None:
    sensors = build_temperature_sensors()
    feed(sensors, 1.0, 21.0)

    assert sensors.on_tick(tick(6.0)) == [record(1.0, 21.0)]


def test_stale_sensor_is_reported_once_and_not_recorded() -> None:
    sensors = build_temperature_sensors()
    feed(sensors, 1.0, 21.0)
    sensors.on_tick(tick(2.0))

    first = sensors.on_tick(tick(6.5))
    second = sensors.on_tick(tick(7.5))

    assert first == [SensorStale(sensor_id=SENSOR_ID)]
    assert second == []


def test_stale_sensor_returning_ends_the_staleness_with_its_duration() -> None:
    sensors = build_temperature_sensors()
    feed(sensors, 1.0, 21.0)
    sensors.on_tick(tick(6.5))

    notices = feed(sensors, 9.0, 22.0)

    assert notices == [SensorStaleEnded(sensor_id=SENSOR_ID, duration_ns=3 * NS_PER_S)]
    assert sensors.on_tick(tick(9.5)) == [record(9.0, 22.0)]


def test_sensor_never_seen_is_reported_stale_after_the_limit_from_the_start() -> None:
    sensors = build_temperature_sensors(started_mono_ns=10 * NS_PER_S)

    before = sensors.on_tick(tick(15.0))
    after = sensors.on_tick(tick(15.5))

    assert before == []
    assert after == [SensorStale(sensor_id=SENSOR_ID)]


def test_sensor_never_seen_that_appears_later_ends_the_staleness_from_the_limit() -> None:
    sensors = build_temperature_sensors()
    sensors.on_tick(tick(6.0))

    notices = feed(sensors, 8.0, 21.0)

    assert notices == [SensorStaleEnded(sensor_id=SENSOR_ID, duration_ns=3 * NS_PER_S)]


def test_record_interval_longer_than_the_tick_records_every_nth_tick() -> None:
    sensors = build_temperature_sensors(record_interval_ns=3 * NS_PER_S)
    recorded_at = []

    for second in range(1, 8):
        feed(sensors, second - 0.5, float(second))
        if sensors.on_tick(tick(float(second))):
            recorded_at.append(second)

    assert recorded_at == [1, 4, 7]


def test_record_interval_tolerates_a_tick_up_to_half_a_tick_early() -> None:
    sensors = build_temperature_sensors(record_interval_ns=3 * NS_PER_S)
    feed(sensors, 0.5, 20.0)
    sensors.on_tick(tick(1.0))
    feed(sensors, 3.0, 21.0)

    too_early = sensors.on_tick(tick(3.4))
    in_time = sensors.on_tick(tick(3.5))

    assert (too_early, in_time) == ([], [record(3.0, 21.0)])


def test_record_interval_shorter_than_the_tick_records_on_every_tick() -> None:
    sensors = build_temperature_sensors(record_interval_ns=NS_PER_S // 10)
    feed(sensors, 0.5, 20.0)
    first = sensors.on_tick(tick(1.0))
    feed(sensors, 1.5, 21.0)

    second = sensors.on_tick(tick(2.0))

    assert (first, second) == ([record(0.5, 20.0)], [record(1.5, 21.0)])


def test_unknown_address_is_reported_once_and_recorded_under_its_address() -> None:
    sensors = build_temperature_sensors()

    first = sensors.on_readings(temperature_readings(0.5, (OTHER_ADDRESS, 19.5, None)))
    second = sensors.on_readings(temperature_readings(1.5, (OTHER_ADDRESS, 19.75, None)))

    assert first == [UnknownSensorSeen(address=OTHER_ADDRESS, error_code=None)]
    assert second == []
    assert sensors.on_tick(tick(2.0)) == [
        UnknownSensorRecord(
            address=OTHER_ADDRESS,
            wall_ns=WALL_OFFSET_NS + 1_500_000_000,
            value_c=19.75,
            error=None,
        )
    ]


def test_unknown_address_error_is_recorded_without_an_error_notice() -> None:
    sensors = build_temperature_sensors()

    notices = sensors.on_readings(temperature_readings(0.5, (OTHER_ADDRESS, None, "read_failed")))

    assert notices == [UnknownSensorSeen(address=OTHER_ADDRESS, error_code=None)]
    assert sensors.on_tick(tick(1.0)) == [
        UnknownSensorRecord(
            address=OTHER_ADDRESS,
            wall_ns=WALL_OFFSET_NS + 500_000_000,
            value_c=None,
            error=TemperatureError.READ_FAILED,
        )
    ]


def test_unknown_address_that_disappears_is_reported_gone_and_forgotten() -> None:
    sensors = build_temperature_sensors({})
    sensors.on_readings(temperature_readings(1.0, (OTHER_ADDRESS, 19.5, None)))

    still_there = sensors.on_tick(tick(6.0))
    gone = sensors.on_tick(tick(6.5))
    later = sensors.on_tick(tick(7.5))

    assert [type(item) for item in still_there] == [UnknownSensorRecord]
    assert gone == [UnknownSensorGone(address=OTHER_ADDRESS)]
    assert later == []


def test_unknown_address_returning_after_it_was_forgotten_is_reported_again() -> None:
    sensors = build_temperature_sensors()
    sensors.on_readings(temperature_readings(1.0, (OTHER_ADDRESS, 19.5, None)))
    sensors.on_tick(tick(6.5))

    notices = sensors.on_readings(temperature_readings(9.0, (OTHER_ADDRESS, 19.5, None)))

    assert notices == [UnknownSensorSeen(address=OTHER_ADDRESS, error_code=None)]


def test_known_and_unknown_addresses_in_one_frame_are_handled_independently() -> None:
    sensors = build_temperature_sensors()
    sensors.on_readings(
        temperature_readings(0.5, (SENSOR_ADDRESS, 21.0, None), (OTHER_ADDRESS, 19.0, None))
    )

    outputs = sensors.on_tick(tick(1.0))

    assert [type(item) for item in outputs] == [TemperatureRecord, UnknownSensorRecord]


def test_a_new_unrecognized_code_during_an_error_is_reported_once_and_known_ones_are_not() -> None:
    sensors = build_temperature_sensors()

    notices = [
        feed(sensors, 1.0, None, "read_failed"),
        feed(sensors, 2.0, None, "crc_error"),
        feed(sensors, 3.0, None, "read_failed"),
        feed(sensors, 4.0, None, "crc_error"),
    ]

    assert notices == [
        [
            SensorErrorStarted(
                sensor_id=SENSOR_ID, error=TemperatureError.READ_FAILED, error_code=None
            )
        ],
        [
            SensorErrorStarted(
                sensor_id=SENSOR_ID, error=TemperatureError.UNRECOGNIZED, error_code="crc_error"
            )
        ],
        [],
        [],
    ]


def test_reported_unrecognized_codes_are_forgotten_when_the_error_ends() -> None:
    sensors = build_temperature_sensors()
    feed(sensors, 1.0, None, "crc_error")
    feed(sensors, 2.0, 21.0)

    notices = feed(sensors, 3.0, None, "crc_error")

    assert [type(notice) for notice in notices] == [SensorErrorStarted]


def test_unknown_address_first_seen_with_an_unrecognized_code_reports_the_raw_code() -> None:
    sensors = build_temperature_sensors()

    notices = sensors.on_readings(temperature_readings(0.5, (OTHER_ADDRESS, None, "crc_error")))

    assert notices == [UnknownSensorSeen(address=OTHER_ADDRESS, error_code="crc_error")]
