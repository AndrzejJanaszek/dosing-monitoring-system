import threading
from collections.abc import Iterator, MutableMapping
from typing import Any, cast
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from dms.acquisition import app as app_module
from dms.acquisition.app import AcquisitionApp, build_silos
from dms.acquisition.engine import Engine
from dms.acquisition.ticker import TickTimer
from dms.config.models import (
    AcquisitionConfig,
    BoardConfig,
    EngineConfig,
    MeterConfig,
    SiloConfig,
)
from dms.logs import events
from dms.messages import MeterReading, Tick
from dms.persistence.writer import PostgresRecordStore, Writer
from tests.unit.acquisition.builders import tank_config

RUN_ID = 7
SECOND_NS = 1_000_000_000


class FinishedThreadTarget:
    def run(self) -> None:
        return None


class FakeWriter(FinishedThreadTarget):
    def __init__(self, flushed: bool) -> None:
        self.flushed = flushed


class FakeStore:
    connection = object()


@pytest.fixture
def stopped_runs(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    monkeypatch.setattr(app_module, "stop_run", lambda _connection, run_id: calls.append(run_id))
    return calls


@pytest.fixture
def logs() -> Iterator[list[MutableMapping[str, Any]]]:
    with capture_logs() as captured:
        yield captured


def build(writer_flushed: bool = True) -> AcquisitionApp:
    acquisition = AcquisitionApp(
        adapters=[],
        timer=cast(TickTimer, FinishedThreadTarget()),
        engine=cast(Engine, FinishedThreadTarget()),
        writer=cast(Writer, FakeWriter(writer_flushed)),
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
                format="dgtp",
                frame_end="\r\n",
                reconnect_delay_s=5.0,
                silence_timeout_s=5.0,
            ),
            MeterConfig(
                id="m2",
                port="/dev/m2",
                baudrate=9600,
                format="dgtp",
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
        config, new_event_id=lambda: UUID(int=1), started_wall_ns=100, started_mono_ns=200
    )

    assert {meter_id: silo.silo_id for meter_id, silo in silos.items()} == {"m1": 1, "m2": 2}
    silos["m1"].on_reading(MeterReading("m1", 500, 0, 10 * SECOND_NS))
    assert silos["m1"].on_tick(Tick(0, 12 * SECOND_NS)) != []
    assert silos["m1"].on_tick(Tick(0, 12 * SECOND_NS + 1)) == []
    assert silos["m1"].signals_stale_since_mono_ns == 200 + round(0.5 * SECOND_NS)
