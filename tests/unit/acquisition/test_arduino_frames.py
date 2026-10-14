import pytest

from dms.acquisition.arduino.frames import (
    BoardLogLine,
    PinLevels,
    TemperaturesFrame,
    parse_board_line,
)
from dms.simulator.catalog import ONE_TANK_WITH_SENSORS
from dms.simulator.encoders import banner_lines, encode_pins_frame, encode_temperatures_frame


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (b"[DEBUG] pin: 4", BoardLogLine("DEBUG", "pin: 4")),
        (b"[DEBUG]: i: 3", BoardLogLine("DEBUG", "i: 3")),
        (b"[INFO] ready", BoardLogLine("INFO", "ready")),
        (b"[WARNING] low", BoardLogLine("WARNING", "low")),
        (b"[ERROR] sensor failure", BoardLogLine("ERROR", "sensor failure")),
        (b"[ERROR]", BoardLogLine("ERROR", "")),
        (
            b"[ERROR] TEMP_INTERVAL_MS myst be greater than CONVERSION_TIME_MS!",
            BoardLogLine("ERROR", "TEMP_INTERVAL_MS myst be greater than CONVERSION_TIME_MS!"),
        ),
        (
            b"[WARNING] Default conversation time. PRECISION not set or wrong value.",
            BoardLogLine("WARNING", "Default conversation time. PRECISION not set or wrong value."),
        ),
        (
            b"[DEBUG]: i:0 Address: 28A8F126AB240B1C temp: 21.50",
            BoardLogLine("DEBUG", "i:0 Address: 28A8F126AB240B1C temp: 21.50"),
        ),
        (b"[DEBUG] pin: 4 value: 1", BoardLogLine("DEBUG", "pin: 4 value: 1")),
        (
            b"[DEBUG] REGISTERED io-pin (INPUT_PULLUP) - on pin: 4",
            BoardLogLine("DEBUG", "REGISTERED io-pin (INPUT_PULLUP) - on pin: 4"),
        ),
        (
            b"[DEBUG] Locating devices...Found 2 devices.",
            BoardLogLine("DEBUG", "Locating devices...Found 2 devices."),
        ),
        (
            b"[DEBUG] Found device 0 with address: 28A8F126AB240B1C",
            BoardLogLine("DEBUG", "Found device 0 with address: 28A8F126AB240B1C"),
        ),
        (
            b"[DEBUG] Found ghost device at 1 but could not detect address."
            b" Check power and cabling[DEBUG] Found device 0 with address: 28A8F126AB240B1C",
            BoardLogLine(
                "DEBUG",
                "Found ghost device at 1 but could not detect address."
                " Check power and cabling[DEBUG] Found device 0 with address: 28A8F126AB240B1C",
            ),
        ),
    ],
)
def test_log_lines_carry_level_and_message(line: bytes, expected: BoardLogLine) -> None:
    assert parse_board_line(line) == expected


def test_pins_frame_gives_levels() -> None:
    line = b'{"pins":{"4":1,"5":0,"6":1,"7":1,"8":0,"9":1}}'

    assert parse_board_line(line) == PinLevels({4: 1, 5: 0, 6: 1, 7: 1, 8: 0, 9: 1})


def test_temperatures_frame_carries_no_content() -> None:
    line = b'{"temps":[{"a":"28A8F126AB240B1C","t":21.50}]}'

    assert parse_board_line(line) == TemperaturesFrame()


def test_empty_temperatures_frame_is_accepted() -> None:
    assert parse_board_line(b'{"temps":[]}') == TemperaturesFrame()


@pytest.mark.parametrize(
    "line",
    [
        b"",
        b'{"pins":{"4":1',
        b'{"pins":{"4":true}}',
        b'{"pins":{"4":2}}',
        b'{"pins":{"4":1.0}}',
        b'{"pins":{"x":1}}',
        b'{"pins":{"":1}}',
        b'{"pins":{"\xd9\xa4":1}}',
        b'{"pins":[1,0]}',
        b'{"temps":null}',
        b'{"temps":5}',
        b'{"x":{"4":1}}',
        b'{"pins":{"4":1},"temps":[]}',
        b"[TRACE] something",
        b"[DEBUG",
        b"hello",
        b"42",
        b"[1,2]",
        b"\xff\xfe",
    ],
)
def test_other_lines_are_rejected(line: bytes) -> None:
    assert parse_board_line(line) is None


def test_non_ascii_digits_in_pin_keys_are_rejected() -> None:
    assert parse_board_line('{"pins":{"٤":1}}'.encode()) is None


def test_simulator_frames_are_understood() -> None:
    pins = encode_pins_frame(((4, 0), (5, 1))).removesuffix(b"\r\n")
    temperatures = encode_temperatures_frame((("28A8F126AB240B1C", 21.5),)).removesuffix(b"\r\n")

    assert parse_board_line(pins) == PinLevels({4: 0, 5: 1})
    assert parse_board_line(temperatures) == TemperaturesFrame()


def test_every_simulator_banner_line_is_a_log_line() -> None:
    lines = banner_lines(ONE_TANK_WITH_SENSORS.board)

    parsed = [parse_board_line(line.encode("ascii")) for line in lines]

    assert all(isinstance(item, BoardLogLine) for item in parsed)
