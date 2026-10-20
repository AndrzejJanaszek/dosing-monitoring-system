import heapq
import queue
import threading
from collections.abc import Iterator, MutableMapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.rows import TupleRow
from structlog.testing import capture_logs

from dms.acquisition.app import board_wiring, build_temperature_sensors
from dms.acquisition.engine import Engine
from dms.acquisition.startup import run_startup_sequence
from dms.config.models import AcquisitionConfig, TemperaturesConfig
from dms.domain.records import TemperatureRecord, UnknownSensorRecord, WriterRecord
from dms.domain.temperature_error import TemperatureError
from dms.logs import events
from dms.messages import EngineMessage, Tick
from dms.persistence.record_store import EPOCH, PostgresRecordStore
from dms.simulator.catalog import SCENARIOS
from dms.simulator.dms_config import acquisition_config
from dms.simulator.encoders import encode_banner, encode_sample
from dms.simulator.expected_temperatures import (
    ExpectedTemperatureRow,
    TemperatureExpectations,
    expected_temperature_rows,
)
from dms.simulator.scenario import Scenario
from dms.simulator.timeline import Sample, TemperaturesSample, scenario_samples
from dms.units import NS_PER_S, NS_PER_US
from tests.database import connect_as, migrate_as_owner

WRITER_ROLE = "dms_writer"
TEMPERATURE_SCENARIOS = [name for name in SCENARIOS if name.startswith("temperatures-")]
SENSOR_STATE_EVENTS = (
    events.TEMPERATURE_SENSOR_ERROR,
    events.TEMPERATURE_SENSOR_ERROR_ENDED,
    events.TEMPERATURE_STALE,
    events.TEMPERATURE_STALE_ENDED,
    events.TEMPERATURE_UNKNOWN_SENSOR,
    events.TEMPERATURE_UNKNOWN_SENSOR_GONE,
)
LONG_RECORD_INTERVAL_S = 3.0


def merged(
    tick_times_ns: range, samples: list[Sample]
) -> Iterator[tuple[int, int, int | TemperaturesSample]]:
    ticks = ((tick_ns, 0, tick_ns) for tick_ns in tick_times_ns)
    readings = (
        (sample.at_ns, 1, sample) for sample in samples if isinstance(sample, TemperaturesSample)
    )
    return heapq.merge(ticks, readings, key=lambda item: (item[0], item[1]))


def tick_times_of(scenario: Scenario, config: AcquisitionConfig) -> range:
    return range(0, scenario.duration_ns + 1, round(config.engine.tick_interval_s * NS_PER_S))


def run_pipeline(
    scenario: Scenario, samples: list[Sample], config: AcquisitionConfig
) -> list[WriterRecord]:
    assert config.board is not None
    messages: queue.Queue[EngineMessage] = queue.Queue()
    writer_queue: queue.Queue[WriterRecord] = queue.Queue()
    engine = Engine(
        in_queue=queue.Queue(),
        out_queue=writer_queue,
        silos_by_meter={},
        stop_event=threading.Event(),
        temperatures=build_temperature_sensors(config, started_mono_ns=0),
    )
    framer, handler = board_wiring(config.board, config.tanks, messages)
    for frame in framer.feed(encode_banner(scenario.layout.board)):
        handler.handle(frame, 0, 0)

    for at_ns, _, item in merged(tick_times_of(scenario, config), samples):
        if isinstance(item, int):
            engine.handle(Tick(at_ns, at_ns))
            continue
        _, data = encode_sample(item, scenario.layout)
        for frame in framer.feed(data):
            handler.handle(frame, at_ns, at_ns)
        while not messages.empty():
            engine.handle(messages.get_nowait())

    records: list[WriterRecord] = []
    while not writer_queue.empty():
        records.append(writer_queue.get_nowait())
    return records


def expectations_of(config: AcquisitionConfig) -> TemperatureExpectations:
    settings = config.temperatures
    return TemperatureExpectations(
        tick_interval_ns=round(config.engine.tick_interval_s * NS_PER_S),
        record_interval_ns=round(settings.record_interval_s * NS_PER_S),
        max_reading_age_ns=round(settings.max_reading_age_s * NS_PER_S),
        min_valid_c=settings.min_valid_c,
        max_valid_c=settings.max_valid_c,
    )


def oracle_rows(
    scenario: Scenario, samples: list[Sample], config: AcquisitionConfig
) -> list[ExpectedTemperatureRow]:
    return expected_temperature_rows(
        scenario.layout,
        samples,
        tick_times_ns=tick_times_of(scenario, config),
        expectations=expectations_of(config),
    )


def wall_ns_of(moment: datetime) -> int:
    return (moment - EPOCH) // timedelta(microseconds=1) * NS_PER_US


def error_of(raw: str | None) -> TemperatureError | None:
    return None if raw is None else TemperatureError(raw)


def stored_rows(
    reader: psycopg.Connection[TupleRow], config: AcquisitionConfig
) -> list[ExpectedTemperatureRow]:
    address_by_id = {sensor.id: sensor.address for sensor in config.temperature_sensors}
    known = [
        ExpectedTemperatureRow(
            sensor_id=sensor_id,
            address=address_by_id[sensor_id],
            wall_ns=wall_ns_of(moment),
            value_c=value_c,
            error=error_of(error),
        )
        for sensor_id, moment, value_c, error in reader.execute(
            "SELECT sensor_id, t, value_c, error FROM dms.temperature_reading"
        )
    ]
    unknown = [
        ExpectedTemperatureRow(
            sensor_id=None,
            address=address,
            wall_ns=wall_ns_of(moment),
            value_c=value_c,
            error=error_of(error),
        )
        for address, moment, value_c, error in reader.execute(
            "SELECT address, t, value_c, error FROM dms.unknown_sensor_reading"
        )
    ]
    return sorted([*known, *unknown], key=lambda row: (row.wall_ns, row.address))


def store_records(
    database_url: str, config: AcquisitionConfig, records: list[WriterRecord]
) -> None:
    with connect_as(database_url, WRITER_ROLE) as connection:
        run_id = run_startup_sequence(connection, config)
        store = PostgresRecordStore(
            connection, lambda: connect_as(database_url, WRITER_ROLE), run_id
        )
        store.write(records)


@pytest.mark.parametrize("name", TEMPERATURE_SCENARIOS)
def test_stored_temperature_rows_of_every_scenario_match_the_oracle(
    name: str, fresh_database: str, tmp_path: Path
) -> None:
    migrate_as_owner(fresh_database)
    scenario = SCENARIOS[name]
    config = acquisition_config(scenario.layout, tmp_path)
    samples = list(scenario_samples(scenario))

    records = run_pipeline(scenario, samples, config)
    store_records(fresh_database, config, records)

    expected = oracle_rows(scenario, samples, config)
    assert expected
    with psycopg.connect(fresh_database) as reader:
        assert stored_rows(reader, config) == expected


def test_records_of_the_pipeline_are_exactly_the_expected_rows(tmp_path: Path) -> None:
    scenario = SCENARIOS["temperatures-sensor-errors"]
    config = acquisition_config(scenario.layout, tmp_path)
    samples = list(scenario_samples(scenario))

    records = run_pipeline(scenario, samples, config)

    produced = [
        (record.wall_ns, record.error)
        for record in records
        if isinstance(record, TemperatureRecord)
    ]
    assert produced == [(row.wall_ns, row.error) for row in oracle_rows(scenario, samples, config)]
    assert not [record for record in records if isinstance(record, UnknownSensorRecord)]


def test_rows_follow_the_oracle_with_a_record_interval_longer_than_the_tick(
    fresh_database: str, tmp_path: Path
) -> None:
    migrate_as_owner(fresh_database)
    scenario = SCENARIOS["temperatures-rising"]
    config = acquisition_config(scenario.layout, tmp_path).model_copy(
        update={"temperatures": TemperaturesConfig(record_interval_s=LONG_RECORD_INTERVAL_S)}
    )
    samples = list(scenario_samples(scenario))

    records = run_pipeline(scenario, samples, config)
    store_records(fresh_database, config, records)

    expected = oracle_rows(scenario, samples, config)
    assert 0 < len(expected) < scenario.duration_ns // NS_PER_S
    with psycopg.connect(fresh_database) as reader:
        assert stored_rows(reader, config) == expected


def test_unknown_sensor_readings_never_reach_the_sensor_table(
    fresh_database: str, tmp_path: Path
) -> None:
    migrate_as_owner(fresh_database)
    scenario = SCENARIOS["temperatures-unknown-sensor"]
    config = acquisition_config(scenario.layout, tmp_path)
    samples = list(scenario_samples(scenario))

    store_records(fresh_database, config, run_pipeline(scenario, samples, config))

    with psycopg.connect(fresh_database) as reader:
        assert reader.execute(
            "SELECT DISTINCT sensor_id FROM dms.temperature_reading"
        ).fetchall() == [(1,)]
        assert reader.execute(
            "SELECT DISTINCT address FROM dms.unknown_sensor_reading"
        ).fetchall() == [("28B3C41D5E6F7A80",)]


def state_logs(scenario_name: str, tmp_path: Path) -> list[MutableMapping[str, Any]]:
    scenario = SCENARIOS[scenario_name]
    config = acquisition_config(scenario.layout, tmp_path)
    samples = list(scenario_samples(scenario))
    with capture_logs() as logs:
        run_pipeline(scenario, samples, config)
    return [entry for entry in logs if entry["event"] in SENSOR_STATE_EVENTS]


@pytest.mark.parametrize("name", ["temperatures-rising", "temperatures-ambient-sensor"])
def test_healthy_sensors_log_nothing(name: str, tmp_path: Path) -> None:
    assert state_logs(name, tmp_path) == []


def test_each_sensor_error_is_logged_when_it_starts_and_ends(tmp_path: Path) -> None:
    logs = state_logs("temperatures-sensor-errors", tmp_path)

    starts = [entry for entry in logs if entry["event"] == events.TEMPERATURE_SENSOR_ERROR]
    ends = [entry for entry in logs if entry["event"] == events.TEMPERATURE_SENSOR_ERROR_ENDED]
    assert [entry["error"] for entry in starts] == [
        TemperatureError.READ_FAILED,
        TemperatureError.POWER_RESET,
        TemperatureError.INSUFFICIENT_POWER,
        TemperatureError.UNRECOGNIZED,
    ]
    assert [entry.get("error_code") for entry in starts] == [None, None, None, "crc_error"]
    assert [entry["duration_s"] for entry in ends] == [2.0] * 4
    assert len(logs) == 8


def test_out_of_range_values_are_logged_as_sensor_errors(tmp_path: Path) -> None:
    logs = state_logs("temperatures-out-of-range", tmp_path)

    assert [entry["event"] for entry in logs] == [
        events.TEMPERATURE_SENSOR_ERROR,
        events.TEMPERATURE_SENSOR_ERROR_ENDED,
    ] * 3
    assert {entry["error"] for entry in logs if "error" in entry} == {
        TemperatureError.OUT_OF_RANGE
    }


def test_missing_sensor_is_logged_stale_once_and_back_with_its_duration(tmp_path: Path) -> None:
    logs = state_logs("temperatures-sensor-missing-and-back", tmp_path)

    assert [(entry["event"], entry["sensor_id"]) for entry in logs] == [
        (events.TEMPERATURE_STALE, 1),
        (events.TEMPERATURE_STALE_ENDED, 1),
    ]
    assert logs[1]["duration_s"] == 6.0


def test_unknown_address_is_logged_when_it_appears_disappears_and_returns(
    tmp_path: Path,
) -> None:
    logs = state_logs("temperatures-unknown-sensor", tmp_path)

    assert [(entry["event"], entry["address"]) for entry in logs] == [
        (events.TEMPERATURE_UNKNOWN_SENSOR, "28B3C41D5E6F7A80"),
        (events.TEMPERATURE_UNKNOWN_SENSOR_GONE, "28B3C41D5E6F7A80"),
        (events.TEMPERATURE_UNKNOWN_SENSOR, "28B3C41D5E6F7A80"),
    ]
