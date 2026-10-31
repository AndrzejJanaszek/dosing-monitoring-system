import threading
from collections.abc import MutableMapping
from typing import Any, cast
from uuid import UUID

import pytest

from dms.acquisition import app as app_module
from dms.acquisition.app import AcquisitionApp, build_silos, build_temperature_sensors
from dms.acquisition.engine import Engine
from dms.acquisition.ticker import TickTimer
from dms.config.models import (
    AcquisitionConfig,
    BoardConfig,
    EngineConfig,
    MeterConfig,
    MeterFormat,
    SiloConfig,
    TemperaturesConfig,
    TemperatureSensorConfig,
)
from dms.domain.temperature_error import TemperatureError
from dms.logs import events
from dms.messages import MeterReading, TemperatureEntry, TemperatureReadings, Tick
from dms.persistence.record_store import PostgresRecordStore
from dms.persistence.writer import Writer
from dms.units import NS_PER_S
from tests.unit.acquisition.builders import tank_config

RUN_ID = 7


class FinishedThreadTarget:
    def run(self) -> None:
        return None


class FakeWriter(FinishedThreadTarget):
    def __init__(self, *, flushed: bool) -> None:
        self.flushed = flushed


class FakeStore:
    connection = object()


@pytest.fixture
def stopped_runs(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    monkeypatch.setattr(app_module, "stop_run", lambda _connection, run_id: calls.append(run_id))
    return calls


def build(*, writer_flushed: bool = True) -> AcquisitionApp:
    acquisition = AcquisitionApp(
        adapters=[],
        timer=cast(TickTimer, FinishedThreadTarget()),
        engine=cast(Engine, FinishedThreadTarget()),
        writer=cast(Writer, FakeWriter(flushed=writer_flushed)),
        store=cast(PostgresRecordStore, FakeStore()),
        run_id=RUN_ID,
        producers_stop=threading.Event(),
        engine_stop=threading.Event(),
        writer_stop=threading.Event(),
    )
    acquisition.start()
    return acquisition


def test_clean_stop_closes_the_run(stopped_runs: list[int]) -> None:
    acquisition = build()

    acquisition.stop()

    assert stopped_runs == [RUN_ID]
    assert not acquisition.failed


def test_lost_records_leave_the_run_open(
    stopped_runs: list[int], logs: list[MutableMapping[str, Any]]
) -> None:
    acquisition = build(writer_flushed=False)

    acquisition.stop()

    assert stopped_runs == []
    assert acquisition.failed
    assert [entry["event"] for entry in logs] == [events.SERVICE_STOP_INCOMPLETE]


def test_crashed_thread_leaves_the_run_open(stopped_runs: list[int]) -> None:
    acquisition = build()
    acquisition.fail()

    acquisition.stop()

    assert stopped_runs == []
    assert acquisition.failed


def test_wait_returns_after_shutdown_request() -> None:
    acquisition = build()
    threading.Timer(0.01, acquisition.request_shutdown).start()

    acquisition.wait()


def test_build_silos_assigns_each_silo_its_own_tanks_and_config_ages() -> None:
    config = AcquisitionConfig(
        engine=EngineConfig(max_reading_age_s=2.0, max_signal_age_s=0.5),
        meters=(
            MeterConfig(
                id="m1",
                port="/dev/m1",
                baudrate=9600,
                format=MeterFormat.DGTP,
                frame_end="\r\n",
                reconnect_delay_s=5.0,
                silence_timeout_s=5.0,
            ),
            MeterConfig(
                id="m2",
                port="/dev/m2",
                baudrate=9600,
                format=MeterFormat.DGTP,
                frame_end="\r\n",
                reconnect_delay_s=5.0,
                silence_timeout_s=5.0,
            ),
        ),
        silos=(
            SiloConfig(id=1, name="Silos 1", meter_id="m1"),
            SiloConfig(id=2, name="Silos 2", meter_id="m2"),
        ),
        board=BoardConfig(
            id="board",
            port="/dev/board",
            baudrate=9600,
            frame_end="\r\n",
            reconnect_delay_s=5.0,
            silence_timeout_s=5.0,
        ),
        tanks=(tank_config(1, 4, 5), tank_config(2, 6, 7)),
    )

    silos = build_silos(
        config,
        new_event_id=lambda: UUID(int=1),
        started_wall_ns=100,
        started_mono_ns=200,
        rate_samples={},
    )

    assert {meter_id: silo.silo_id for meter_id, silo in silos.items()} == {"m1": 1, "m2": 2}
    silos["m1"].on_reading(
        MeterReading(meter_id="m1", value_kg=500, wall_ns=0, mono_ns=10 * NS_PER_S)
    )
    assert silos["m1"].on_tick(Tick(0, 12 * NS_PER_S)) != []
    assert silos["m1"].on_tick(Tick(0, 12 * NS_PER_S + 1)) == []
    assert silos["m1"].signals_stale_since_mono_ns == 200 + round(0.5 * NS_PER_S)


def temperature_config(*, with_board: bool) -> AcquisitionConfig:
    return AcquisitionConfig(
        engine=EngineConfig(tick_interval_s=2.0),
        temperatures=TemperaturesConfig(
            record_interval_s=10.0, max_reading_age_s=3.0, min_valid_c=-10.0, max_valid_c=50.0
        ),
        meters=(),
        silos=(),
        board=BoardConfig(
            id="board",
            port="/dev/board",
            baudrate=9600,
            frame_end="\r\n",
            reconnect_delay_s=5.0,
            silence_timeout_s=5.0,
        )
        if with_board
        else None,
        temperature_sensors=(
            TemperatureSensorConfig(id=4, name="Czujnik 4", address="28A8F126AB240B1C"),
        ),
    )


def test_board_without_temperature_sensors_still_builds_temperature_tracking() -> None:
    config = temperature_config(with_board=True).model_copy(update={"temperature_sensors": ()})

    assert build_temperature_sensors(config, started_mono_ns=0) is not None


def test_no_temperature_tracking_without_a_board() -> None:
    assert (
        build_temperature_sensors(temperature_config(with_board=False), started_mono_ns=0) is None
    )


def test_temperature_tracking_follows_the_configured_settings() -> None:
    sensors = build_temperature_sensors(temperature_config(with_board=True), started_mono_ns=0)
    assert sensors is not None
    sensors.on_readings(
        TemperatureReadings((TemperatureEntry("28A8F126AB240B1C", 60.0, None),), 1, 1 * NS_PER_S)
    )

    first = sensors.on_tick(Tick(2, 2 * NS_PER_S))
    stale = sensors.on_tick(Tick(5, 5 * NS_PER_S))

    assert [getattr(item, "error", None) for item in first] == [TemperatureError.OUT_OF_RANGE]
    assert [type(item).__name__ for item in stale] == ["SensorStale"]
