import json
import os
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from dms.acquisition.clock import NS_PER_S
from dms.acquisition.meters.dgtp import parse_dgtp_frame
from dms.simulator.catalog import SCENARIOS
from dms.simulator.timeline import MeterSample, scenario_samples
from dms.simulator.transport import PseudoTerminal, SimulationRunner

READ_CHUNK_BYTES = 65536
FRAME_TERMINATOR = b"\r\n"
UNREAD_LIMIT_S = 600
ADVANCE_STEP_S = 1.0
BANNER_PREFIX = b"[DEBUG]"
BACKGROUND_FRAMES = 3
BACKGROUND_TIMEOUT_S = 5.0
BACKGROUND_POLL_S = 0.05


class FakeClock:
    def __init__(self) -> None:
        self.now_ns = 0

    def __call__(self) -> int:
        return self.now_ns

    def advance(self, seconds: float) -> None:
        self.now_ns += round(seconds * NS_PER_S)


class PortReader:
    def __init__(self, path: Path) -> None:
        self._fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY)
        self.received = b""

    def drain(self) -> None:
        while True:
            try:
                chunk = os.read(self._fd, READ_CHUNK_BYTES)
            except BlockingIOError:
                return
            if not chunk:
                return
            self.received += chunk

    def lines(self) -> list[bytes]:
        return self.received.split(FRAME_TERMINATOR)[:-1]

    def close(self) -> None:
        os.close(self._fd)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def runner(tmp_path: Path, clock: FakeClock) -> Iterator[SimulationRunner]:
    simulation = SimulationRunner(SCENARIOS["dispense-single"], tmp_path / "ports", clock)
    simulation.open()
    yield simulation
    simulation.stop()


@pytest.fixture
def meter(runner: SimulationRunner) -> Iterator[PortReader]:
    reader = PortReader(runner.ports["meter-1"].path)
    yield reader
    reader.close()


@pytest.fixture
def arduino(runner: SimulationRunner) -> Iterator[PortReader]:
    reader = PortReader(runner.ports["arduino"].path)
    yield reader
    reader.close()


def advance_and_step(runner: SimulationRunner, clock: FakeClock, seconds: float) -> None:
    clock.advance(seconds)
    runner.step()


def test_links_point_to_the_pseudo_terminals(runner: SimulationRunner, tmp_path: Path) -> None:
    for device_id, port in runner.ports.items():
        assert (tmp_path / "ports" / device_id).resolve() == port.path.resolve()


def test_meter_frames_match_the_scenario_samples(
    runner: SimulationRunner, clock: FakeClock, meter: PortReader
) -> None:
    runner.start_scenario()
    runner.step()
    for _ in range(46):
        advance_and_step(runner, clock, 1.0)
        meter.drain()

    expected = [
        s.value_kg
        for s in scenario_samples(SCENARIOS["dispense-single"])
        if isinstance(s, MeterSample)
    ]
    received = [parse_dgtp_frame(line) for line in meter.lines() if line]
    assert received[: len(expected)] == expected
    assert set(received[len(expected) :]) == {18_500}


def test_banner_comes_before_the_first_pins_frame(
    runner: SimulationRunner, clock: FakeClock, arduino: PortReader
) -> None:
    runner.step()
    arduino.drain()

    lines = arduino.lines()
    first_frame = next(index for index, line in enumerate(lines) if line.startswith(b"{"))
    assert all(line.startswith(BANNER_PREFIX) for line in lines[:first_frame])
    assert first_frame == 7
    assert json.loads(lines[first_frame])["pins"]["4"] == 1


def test_unread_port_drops_whole_frames_and_does_not_block_the_meter(
    runner: SimulationRunner, clock: FakeClock, meter: PortReader, arduino: PortReader
) -> None:
    unread = runner.ports["arduino"]
    runner.step()
    elapsed_s = 0.0
    while unread.dropped_frames == 0 and elapsed_s < UNREAD_LIMIT_S:
        advance_and_step(runner, clock, ADVANCE_STEP_S)
        meter.drain()
        elapsed_s += ADVANCE_STEP_S
    assert unread.dropped_frames > 0

    arduino.drain()
    advance_and_step(runner, clock, ADVANCE_STEP_S)
    arduino.drain()
    meter.drain()

    assert runner.ports["meter-1"].dropped_frames == 0
    assert arduino.received.endswith(FRAME_TERMINATOR)
    for line in arduino.lines():
        assert line.startswith(BANNER_PREFIX) or json.loads(line).keys() <= {"pins", "temps"}
    assert all(parse_dgtp_frame(line) == 20_000 for line in meter.lines())
    assert len(meter.lines()) >= elapsed_s * 10


def test_frames_sent_without_a_reader_are_not_delivered_later(
    runner: SimulationRunner, clock: FakeClock
) -> None:
    runner.step()
    for _ in range(30):
        advance_and_step(runner, clock, 1.0)

    meter = PortReader(runner.ports["meter-1"].path)
    try:
        meter.drain()
        assert meter.received == b""

        advance_and_step(runner, clock, 0.1)
        meter.drain()
        assert len(meter.lines()) == 1
    finally:
        meter.close()


def test_reconnected_reader_gets_the_banner_and_no_stale_frames(
    runner: SimulationRunner, clock: FakeClock
) -> None:
    first = PortReader(runner.ports["arduino"].path)
    runner.step()
    advance_and_step(runner, clock, 1.0)
    first.close()

    for _ in range(30):
        advance_and_step(runner, clock, 1.0)

    second = PortReader(runner.ports["arduino"].path)
    try:
        advance_and_step(runner, clock, 0.25)
        second.drain()
        lines = second.lines()
        assert all(line.startswith(BANNER_PREFIX) for line in lines[:7])
        assert [line for line in lines[7:] if not line.startswith(b"{")] == []
        assert len(lines) == 8
    finally:
        second.close()


def test_resting_grid_starts_when_the_ports_open(tmp_path: Path, clock: FakeClock) -> None:
    simulation = SimulationRunner(SCENARIOS["idle"], tmp_path / "ports", clock)
    clock.advance(30.0)
    simulation.open()
    meter = PortReader(simulation.ports["meter-1"].path)
    try:
        simulation.step()
        meter.drain()
        assert len(meter.lines()) == 1
    finally:
        meter.close()
        simulation.stop()


def test_stopping_twice_closes_the_ports_once(tmp_path: Path, clock: FakeClock) -> None:
    simulation = SimulationRunner(SCENARIOS["idle"], tmp_path / "ports", clock)
    simulation.open()

    simulation.stop()
    simulation.stop()

    assert simulation.ports == {}


def test_start_scenario_restarts_the_grid_and_holds_the_final_state(
    runner: SimulationRunner, clock: FakeClock, meter: PortReader
) -> None:
    clock.advance(7.3)
    runner.step()
    meter.drain()
    resting_frames = len(meter.lines())

    runner.start_scenario()
    runner.step()
    meter.drain()
    assert len(meter.lines()) == resting_frames + 1
    assert not runner.scenario_finished.is_set()

    for _ in range(60):
        advance_and_step(runner, clock, 1.0)
        meter.drain()

    assert runner.scenario_finished.is_set()
    assert parse_dgtp_frame(meter.lines()[-1]) == 18_500


def test_stop_removes_the_links(tmp_path: Path, clock: FakeClock) -> None:
    simulation = SimulationRunner(SCENARIOS["idle"], tmp_path / "ports", clock)
    simulation.open()
    assert (tmp_path / "ports" / "meter-1").is_symlink()

    simulation.stop()

    assert not (tmp_path / "ports" / "meter-1").exists()
    assert not (tmp_path / "ports" / "arduino").exists()


def test_background_thread_runs_and_stops(tmp_path: Path) -> None:
    simulation = SimulationRunner(SCENARIOS["idle"], tmp_path / "ports")
    simulation.open()
    reader = PortReader(simulation.ports["meter-1"].path)
    simulation.start()
    try:
        deadline = time.monotonic() + BACKGROUND_TIMEOUT_S
        while len(reader.lines()) < BACKGROUND_FRAMES and time.monotonic() < deadline:
            reader.drain()
            time.sleep(BACKGROUND_POLL_S)
        assert len(reader.lines()) >= BACKGROUND_FRAMES
    finally:
        simulation.stop()
        reader.close()

    assert not (tmp_path / "ports" / "meter-1").exists()


def test_pseudo_terminal_without_link_exposes_its_path() -> None:
    terminal = PseudoTerminal()
    try:
        assert terminal.path.exists()
    finally:
        terminal.close()
