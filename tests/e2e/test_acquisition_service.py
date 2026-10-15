import itertools
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import TupleRow

from dms.simulator.catalog import SCENARIOS
from dms.simulator.dms_config import acquisition_config, render_acquisition_toml
from dms.simulator.timeline import MeterSample, scenario_samples
from dms.simulator.transport import SimulationRunner
from tests.database import migrate_as_owner

ROLE_PASSWORD = "dms"
SERVICE_SCRIPT = Path(sys.executable).parent / "dms-acquisition"
POLL_INTERVAL_S = 0.2
STARTUP_TIMEOUT_S = 20.0
SHUTDOWN_TIMEOUT_S = 10.0
SCENARIO_TIMEOUT_S = 20.0
RECONNECT_DELAY_S = 1.0
SCENARIO_NAME = "dispense-short"
MIN_ROWS = 3
IDLE_RUN_SECONDS = 2.5


class Service:
    def __init__(self, process: subprocess.Popen[str], output_path: Path) -> None:
        self.process = process
        self._output_path = output_path

    def output(self) -> str:
        return self._output_path.read_text(encoding="utf-8")

    def terminate(self) -> int:
        self.process.send_signal(signal.SIGTERM)
        try:
            return self.process.wait(SHUTDOWN_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            self.process.kill()
            pytest.fail(f"service did not stop after SIGTERM\n{self.output()}")


def write_shared_config(directory: Path, database_url: str) -> None:
    parameters = conninfo_to_dict(database_url)
    (directory / "shared.toml").write_text(
        f'[database]\nhost = "{parameters["host"]}"\nport = {parameters["port"]}\n'
        f'dbname = "{parameters["dbname"]}"\n[logging]\nformat = "json"\n',
        encoding="utf-8",
    )


def write_acquisition_config(directory: Path, link_dir: Path) -> None:
    config = acquisition_config(
        SCENARIOS[SCENARIO_NAME].layout, link_dir, reconnect_delay_s=RECONNECT_DELAY_S
    )
    (directory / "acquisition.toml").write_text(render_acquisition_toml(config), encoding="utf-8")


@pytest.fixture
def e2e_database(fresh_database: str) -> str:
    migrate_as_owner(fresh_database)
    with psycopg.connect(fresh_database, autocommit=True) as superuser:
        superuser.execute(f"ALTER ROLE dms_writer PASSWORD '{ROLE_PASSWORD}'")
    return fresh_database


def start_service(tmp_path: Path, database_url: str, link_dir: Path) -> Service:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    write_shared_config(config_dir, database_url)
    write_acquisition_config(config_dir, link_dir)
    output_path = tmp_path / "service.log"
    environment = {**os.environ, "DMS_CONFIG_DIR": str(config_dir), "PGPASSWORD": ROLE_PASSWORD}
    with output_path.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            [str(SERVICE_SCRIPT)],
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            text=True,
        )
    return Service(process, output_path)


def poll_until(condition_met: Callable[[], bool], timeout_s: float, failure_message: str) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition_met():
            return
        time.sleep(POLL_INTERVAL_S)
    pytest.fail(failure_message)


def query(database_url: str, statement: str) -> list[TupleRow]:
    with psycopg.connect(database_url) as connection:
        return connection.execute(statement).fetchall()


@pytest.fixture
def simulation(tmp_path: Path) -> Iterator[SimulationRunner]:
    runner = SimulationRunner(SCENARIOS[SCENARIO_NAME], tmp_path / "ports")
    runner.open()
    runner.start()
    yield runner
    runner.stop()


def test_service_records_meter_readings_and_stops_cleanly(
    tmp_path: Path, e2e_database: str, simulation: SimulationRunner
) -> None:
    scenario = SCENARIOS[SCENARIO_NAME]
    start_kg = scenario.start_mass_kg(1)
    end_kg = start_kg - sum(event.mass_kg for event in scenario.events)
    service = start_service(tmp_path, e2e_database, tmp_path / "ports")
    try:
        poll_until(
            lambda: len(query(e2e_database, "SELECT 1 FROM dms.meter_reading")) >= 1,
            STARTUP_TIMEOUT_S,
            f"the service stored no readings\n{service.output()}",
        )
        simulation.start_scenario()
        poll_until(
            lambda: (
                len(query(e2e_database, "SELECT 1 FROM dms.meter_reading")) >= MIN_ROWS
                and any(
                    end_kg < row[0] < start_kg
                    for row in query(e2e_database, "SELECT value_kg FROM dms.meter_reading")
                )
            ),
            SCENARIO_TIMEOUT_S,
            f"the readings did not follow the scenario\n{service.output()}",
        )
    finally:
        exit_code = service.terminate()

    assert exit_code == 0, service.output()
    rows = query(
        e2e_database, "SELECT extract(epoch FROM t), value_kg FROM dms.meter_reading ORDER BY t"
    )
    gaps_s = [float(later[0]) - float(earlier[0]) for earlier, later in itertools.pairwise(rows)]
    assert all(0.7 <= gap <= 1.3 for gap in gaps_s), gaps_s
    sent_values = {
        sample.value_kg for sample in scenario_samples(scenario) if isinstance(sample, MeterSample)
    }
    assert {row[1] for row in rows} <= sent_values
    assert any(end_kg < row[1] < start_kg for row in rows)
    assert query(e2e_database, "SELECT stopped_at IS NOT NULL FROM dms.run") == [(True,)]


def test_service_runs_without_meter_and_stops_cleanly(tmp_path: Path, e2e_database: str) -> None:
    service = start_service(tmp_path, e2e_database, tmp_path / "missing-ports")
    try:
        poll_until(
            lambda: len(query(e2e_database, "SELECT 1 FROM dms.run")) == 1,
            STARTUP_TIMEOUT_S,
            f"service did not start\n{service.output()}",
        )
        time.sleep(IDLE_RUN_SECONDS)
        assert service.process.poll() is None, service.output()
    finally:
        exit_code = service.terminate()

    assert exit_code == 0, service.output()
    assert query(e2e_database, "SELECT count(*) FROM dms.meter_reading") == [(0,)]
    assert query(e2e_database, "SELECT stopped_at IS NOT NULL FROM dms.run") == [(True,)]
    assert "port.open_failed" in service.output()
