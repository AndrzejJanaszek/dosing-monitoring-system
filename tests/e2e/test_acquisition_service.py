import itertools
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import TupleRow

from dms.simulator.catalog import SCENARIOS
from dms.simulator.dms_config import acquisition_config, render_acquisition_toml
from dms.simulator.scenario import Scenario
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
LIFECYCLE_SCENARIO_NAME = "refill-single"
SECOND_RUN = 2
MIN_ROWS = 3
IDLE_RUN_SECONDS = 2.5
TIMING_JITTER_S = 0.5


EXPECTED_DISPENSE_TRANSITIONS = [(None, False), (False, True), (True, False)]


def dispense_transitions(service: Service) -> list[tuple[bool | None, bool]]:
    return [
        (entry["previous"], entry["active"])
        for entry in service.events("signal.changed")
        if entry["tank_id"] == 1 and entry["signal"] == "dispense"
    ]


class Service:
    def __init__(self, process: subprocess.Popen[str], output_path: Path) -> None:
        self.process = process
        self._output_path = output_path

    def output(self) -> str:
        return self._output_path.read_text(encoding="utf-8")

    def events(self, name: str) -> list[dict[str, Any]]:
        return [entry for entry in self._log_entries() if entry["event"] == name]

    def _log_entries(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for line in self.output().splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict) and "event" in entry:
                entries.append(entry)
        return entries

    def kill(self) -> None:
        self.process.kill()
        self.process.wait(SHUTDOWN_TIMEOUT_S)

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


def write_acquisition_config(directory: Path, link_dir: Path, scenario_name: str) -> None:
    config = acquisition_config(
        SCENARIOS[scenario_name].layout, link_dir, reconnect_delay_s=RECONNECT_DELAY_S
    )
    (directory / "acquisition.toml").write_text(render_acquisition_toml(config), encoding="utf-8")


@pytest.fixture
def e2e_database(fresh_database: str) -> str:
    migrate_as_owner(fresh_database)
    with psycopg.connect(fresh_database, autocommit=True) as superuser:
        superuser.execute(f"ALTER ROLE dms_writer PASSWORD '{ROLE_PASSWORD}'")
    return fresh_database


def write_service_config(
    tmp_path: Path, database_url: str, link_dir: Path, scenario_name: str = SCENARIO_NAME
) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    write_shared_config(config_dir, database_url)
    write_acquisition_config(config_dir, link_dir, scenario_name)
    return config_dir


def launch_service(config_dir: Path, output_path: Path) -> Service:
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


def start_service(tmp_path: Path, database_url: str, link_dir: Path) -> Service:
    config_dir = write_service_config(tmp_path, database_url, link_dir)
    return launch_service(config_dir, tmp_path / "service.log")


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


def test_service_records_readings_and_signal_changes_and_stops_cleanly(
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
        poll_until(
            lambda: len(dispense_transitions(service)) >= len(EXPECTED_DISPENSE_TRANSITIONS),
            SCENARIO_TIMEOUT_S,
            f"the signal changes did not follow the scenario\n{service.output()}",
        )
        poll_until(
            lambda: (
                query(e2e_database, "SELECT 1 FROM dms.tank_event WHERE status <> 'in_progress'")
                != []
            ),
            SCENARIO_TIMEOUT_S,
            f"the event did not end\n{service.output()}",
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
    assert dispense_transitions(service) == EXPECTED_DISPENSE_TRANSITIONS
    refill_changes = [
        (entry["previous"], entry["active"])
        for entry in service.events("signal.changed")
        if entry["tank_id"] == 1 and entry["signal"] == "refill"
    ]
    assert refill_changes == [(None, False)]
    assert query(e2e_database, "SELECT id, silo_id, name, active FROM dms.tank") == [
        (1, 1, "Zbiornik 1", True)
    ]
    (stored_config,) = query(e2e_database, "SELECT config FROM dms.run")[0]
    assert {"board", "tanks"} <= stored_config.keys()
    assert not [
        entry for entry in service.events("port.garbage") if entry["device_id"] == "arduino"
    ]
    assert_dispense_event_stored(e2e_database, service, scenario)


def assert_dispense_event_stored(database_url: str, service: Service, scenario: Scenario) -> None:
    (dispense,) = scenario.events
    board = scenario.layout.board
    meter = scenario.layout.silos[0].meter
    start_kg = scenario.start_mass_kg(1)
    end_kg = start_kg - dispense.mass_kg
    rate_kg_per_s = dispense.mass_kg / (dispense.end_s - dispense.start_s)
    end_tolerance_kg = rate_kg_per_s * (1 / meter.rate_hz + TIMING_JITTER_S) + meter.division_kg
    duration_tolerance_s = board.pins_period_s + TIMING_JITTER_S

    (event_row,) = query(
        database_url,
        "SELECT tank_id, type, status, start_quality, end_quality, run_id, start_value_kg,"
        " end_value_kg, duration_ms FROM dms.tank_event",
    )
    tank_id, kind, status, start_quality, end_quality, run_id, *values = event_row
    start_value, end_value, duration_ms = values

    assert (tank_id, kind, status) == (1, "dispense", "completed")
    assert (start_quality, end_quality) == ("fresh", "fresh")
    assert query(database_url, "SELECT id FROM dms.run") == [(run_id,)]
    assert start_value == start_kg
    assert abs(end_value - end_kg) <= end_tolerance_kg
    expected_duration_s = dispense.end_s - dispense.start_s
    assert abs(duration_ms / 1000 - expected_duration_s) <= duration_tolerance_s
    assert len(service.events("event.started")) == 1
    assert len(service.events("event.completed")) == 1
    assert not service.events("event.incomplete")
    assert not service.events("event.orphaned")


def event_rows(database_url: str) -> list[TupleRow]:
    return query(
        database_url,
        "SELECT run_id, status, start_quality, end_quality, start_at, end_at, end_value_kg,"
        " duration_ms FROM dms.tank_event ORDER BY start_at, id",
    )


def test_service_closes_events_after_a_crash_and_when_stopped(
    tmp_path: Path, e2e_database: str
) -> None:
    runner = SimulationRunner(SCENARIOS[LIFECYCLE_SCENARIO_NAME], tmp_path / "ports")
    runner.open()
    runner.start()
    config_dir = write_service_config(
        tmp_path, e2e_database, tmp_path / "ports", LIFECYCLE_SCENARIO_NAME
    )
    first = launch_service(config_dir, tmp_path / "first.log")
    second: Service | None = None

    try:
        poll_until(
            lambda: len(query(e2e_database, "SELECT 1 FROM dms.meter_reading")) >= 1,
            STARTUP_TIMEOUT_S,
            f"the service stored no readings\n{first.output()}",
        )
        runner.start_scenario()
        poll_until(
            lambda: (
                query(
                    e2e_database,
                    "SELECT 1 FROM dms.tank_event WHERE status = 'in_progress'"
                    " AND start_quality = 'fresh'",
                )
                != []
            ),
            SCENARIO_TIMEOUT_S,
            f"the refill did not start\n{first.output()}",
        )
        first.kill()

        second = launch_service(config_dir, tmp_path / "second.log")
        poll_until(
            lambda: (
                len(query(e2e_database, "SELECT 1 FROM dms.run")) == SECOND_RUN
                and query(
                    e2e_database,
                    "SELECT 1 FROM dms.tank_event WHERE start_quality = 'unknown'",
                )
                != []
            ),
            STARTUP_TIMEOUT_S + SCENARIO_TIMEOUT_S,
            f"the restart did not create an orphaned event\n{second.output()}",
        )

        crashed_rows = event_rows(e2e_database)
        exit_code = second.terminate()
    finally:
        first.process.kill()
        if second is not None:
            second.process.kill()
        runner.stop()

    assert exit_code == 0, second.output()

    first_run_id, second_run_id = (
        row[0] for row in query(e2e_database, "SELECT id FROM dms.run ORDER BY id")
    )
    (crashed, orphaned_in_progress) = crashed_rows
    assert crashed[:4] == (first_run_id, "incomplete", "fresh", "service_crashed")
    assert crashed[4] <= crashed[5]
    assert (crashed[6], crashed[7]) == (None, None)

    assert orphaned_in_progress[:4] == (second_run_id, "in_progress", "unknown", None)
    started_second_run_at = query(
        e2e_database, f"SELECT started_at FROM dms.run WHERE id = {second_run_id}"
    )[0][0]
    assert crashed[5] < started_second_run_at
    assert len(second.events("event.crash_closed")) == 1

    stopped = event_rows(e2e_database)[1]
    assert stopped[:4] == (second_run_id, "incomplete", "unknown", "service_stopped")
    assert stopped[5] > started_second_run_at
    assert (stopped[6], stopped[7]) == (None, None)

    assert query(e2e_database, "SELECT id, stopped_at IS NOT NULL FROM dms.run ORDER BY id") == [
        (first_run_id, False),
        (second_run_id, True),
    ]
    assert [entry["end_quality"] for entry in second.events("event.incomplete")] == [
        "service_stopped"
    ]


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
