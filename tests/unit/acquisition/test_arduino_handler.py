import queue
from collections.abc import Iterator, MutableMapping
from typing import Any

import pytest
from structlog.testing import capture_logs

from dms.acquisition.arduino.handler import ArduinoFrameHandler
from dms.acquisition.arduino.mapping import SignalMapper
from dms.acquisition.serial.adapter import FrameOutcome
from dms.logs import events
from dms.messages import EngineMessage, SignalStates, TankSignals
from tests.unit.acquisition.builders import tank_config

ALL_PINS = b'{"pins":{"4":0,"5":1,"6":1,"7":1}}'
PINS_WITHOUT_FIVE = b'{"pins":{"4":0,"6":1,"7":1}}'
PINS_WITHOUT_FIVE_AND_SIX = b'{"pins":{"4":0,"7":1}}'


@pytest.fixture
def logs() -> Iterator[list[MutableMapping[str, Any]]]:
    with capture_logs() as captured:
        yield captured


def build() -> tuple[ArduinoFrameHandler, queue.Queue[EngineMessage]]:
    messages: queue.Queue[EngineMessage] = queue.Queue()
    handler = ArduinoFrameHandler(
        board_id="b1",
        port_name="/dev/fake",
        mapper=SignalMapper([tank_config(1, 4, 5), tank_config(2, 6, 7)]),
        out_queue=messages,
    )
    return handler, messages


def test_complete_pins_frame_publishes_signal_states_with_given_stamps() -> None:
    handler, messages = build()

    outcome = handler.handle(ALL_PINS, 11, 22)

    assert outcome is FrameOutcome.ACCEPTED
    assert messages.get_nowait() == SignalStates(
        (
            TankSignals(1, dispense=True, refill=False),
            TankSignals(2, dispense=False, refill=False),
        ),
        11,
        22,
    )


def test_temperatures_frame_is_accepted_without_publishing() -> None:
    handler, messages = build()

    assert handler.handle(b'{"temps":[]}', 0, 0) is FrameOutcome.ACCEPTED
    assert messages.empty()


def test_unknown_line_is_rejected() -> None:
    handler, messages = build()

    assert handler.handle(b"hello", 0, 0) is FrameOutcome.REJECTED
    assert messages.empty()


@pytest.mark.parametrize(
    ("line", "level"),
    [
        (b"[DEBUG] a", "debug"),
        (b"[INFO] a", "info"),
        (b"[WARNING] a", "warning"),
        (b"[ERROR] a", "error"),
    ],
)
def test_board_log_line_is_logged_at_its_level_and_ignored(
    logs: list[MutableMapping[str, Any]], line: bytes, level: str
) -> None:
    handler, messages = build()

    assert handler.handle(line, 0, 0) is FrameOutcome.IGNORED

    (entry,) = logs
    assert entry["event"] == events.ARDUINO_LOG
    assert entry["log_level"] == level
    assert entry["message"] == "a"
    assert entry["device_id"] == "b1"
    assert messages.empty()


def test_missing_pin_is_ignored_and_warned_once(logs: list[MutableMapping[str, Any]]) -> None:
    handler, messages = build()

    outcomes = [handler.handle(PINS_WITHOUT_FIVE, 0, 0) for _ in range(3)]

    assert outcomes == [FrameOutcome.IGNORED] * 3
    assert messages.empty()
    assert [(entry["event"], entry["pins"]) for entry in logs] == [
        (events.ARDUINO_PINS_MISSING, [5])
    ]


def test_warning_repeats_when_the_set_of_missing_pins_changes(
    logs: list[MutableMapping[str, Any]],
) -> None:
    handler, _ = build()

    handler.handle(PINS_WITHOUT_FIVE, 0, 0)
    handler.handle(PINS_WITHOUT_FIVE_AND_SIX, 0, 0)

    assert [entry["pins"] for entry in logs] == [[5], [5, 6]]


def test_complete_frame_after_missing_pins_logs_restoration_once(
    logs: list[MutableMapping[str, Any]],
) -> None:
    handler, messages = build()
    handler.handle(PINS_WITHOUT_FIVE, 0, 0)

    assert handler.handle(ALL_PINS, 0, 0) is FrameOutcome.ACCEPTED
    handler.handle(ALL_PINS, 0, 0)

    assert [entry["event"] for entry in logs] == [
        events.ARDUINO_PINS_MISSING,
        events.ARDUINO_PINS_RESTORED,
    ]
    assert messages.qsize() == 2
