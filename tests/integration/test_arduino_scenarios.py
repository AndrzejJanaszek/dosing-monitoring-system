import queue
from pathlib import Path

import pytest

from dms.acquisition.arduino.handler import ArduinoFrameHandler
from dms.acquisition.arduino.mapping import SignalMapper
from dms.acquisition.serial.adapter import FrameOutcome
from dms.acquisition.serial.framing import Framer
from dms.domain.events import EventKind
from dms.messages import EngineMessage, SignalStates, TankSignals, TemperatureReadings
from dms.simulator.catalog import SCENARIOS
from dms.simulator.dms_config import acquisition_config
from dms.simulator.encoders import encode_banner, encode_sample
from dms.simulator.plant_state import signal_active
from dms.simulator.scenario import Scenario
from dms.simulator.timeline import PinsSample, TemperaturesSample, scenario_samples


def expected_states(scenario: Scenario, at_ns: int) -> SignalStates:
    tanks = tuple(
        TankSignals(
            tank.id,
            dispense=signal_active(scenario, tank.id, EventKind.DISPENSE, at_ns),
            refill=signal_active(scenario, tank.id, EventKind.REFILL, at_ns),
        )
        for silo in scenario.layout.silos
        for tank in silo.tanks
    )
    return SignalStates(tanks, at_ns, at_ns)


@pytest.mark.parametrize("scenario", SCENARIOS.values(), ids=list(SCENARIOS))
def test_signals_read_from_simulated_board_match_the_scenario(
    scenario: Scenario, tmp_path: Path
) -> None:
    config = acquisition_config(scenario.layout, tmp_path)
    assert config.board is not None
    messages: queue.Queue[EngineMessage] = queue.Queue()
    handler = ArduinoFrameHandler(
        board_id=config.board.id,
        port_name=config.board.port,
        mapper=SignalMapper(config.tanks),
        out_queue=messages,
    )
    framer = Framer(
        config.board.frame_start.encode(),
        config.board.frame_end.encode(),
        config.board.max_frame_length,
    )

    for frame in framer.feed(encode_banner(scenario.layout.board)):
        assert handler.handle(frame, 0, 0) is FrameOutcome.IGNORED

    expected: list[SignalStates] = []
    temperature_frames = 0
    for sample in scenario_samples(scenario):
        if not isinstance(sample, PinsSample | TemperaturesSample):
            continue
        _, data = encode_sample(sample, scenario.layout)
        for frame in framer.feed(data):
            assert handler.handle(frame, sample.at_ns, sample.at_ns) is FrameOutcome.ACCEPTED
        if isinstance(sample, PinsSample):
            expected.append(expected_states(scenario, sample.at_ns))
        else:
            temperature_frames += 1

    received: list[EngineMessage] = []
    while not messages.empty():
        received.append(messages.get_nowait())
    assert expected
    assert framer.rejected_count == 0
    assert [message for message in received if isinstance(message, SignalStates)] == expected
    assert len([message for message in received if isinstance(message, TemperatureReadings)]) == (
        temperature_frames
    )
