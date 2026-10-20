import pytest

from dms.acquisition.arduino.frames import (
    BoardLogLevel,
    BoardLogLine,
    PinLevels,
    TemperatureFrameEntry,
    TemperaturesFrame,
    parse_board_line,
)
from dms.simulator.catalog import ONE_TANK_WITH_SENSORS
from dms.simulator.encoders import banner_lines, encode_pins_frame, encode_temperatures_frame


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (b"[DEBUG] pin: 4", BoardLogLine(BoardLogLevel.DEBUG, "pin: 4")),
        (b"[DEBUG]: i: 3", BoardLogLine(BoardLogLevel.DEBUG, "i: 3")),
        (b"[INFO] ready", BoardLogLine(BoardLogLevel.INFO, "ready")),
        (b"[WARNING] low", BoardLogLine(BoardLogLevel.WARNING, "low")),
        (b"[ERROR] sensor failure", BoardLogLine(BoardLogLevel.ERROR, "sensor failure")),
        (b"[ERROR]", BoardLogLine(BoardLogLevel.ERROR, "")),
        (
            b"[ERROR] TEMP_INTERVAL_MS myst be greater than CONVERSION_TIME_MS!",
            BoardLogLine(
                BoardLogLevel.ERROR, "TEMP_INTERVAL_MS myst be greater than CONVERSION_TIME_MS!"
            ),
        ),
        (
            b"[WARNING] Default conversation time. PRECISION not set or wrong value.",
            BoardLogLine(
                BoardLogLevel.WARNING,
                "Default conversation time. PRECISION not set or wrong value.",
            ),
        ),
        (
            b"[DEBUG]: i:0 Address: 28A8F126AB240B1C temp: 21.50",
            BoardLogLine(BoardLogLevel.DEBUG, "i:0 Address: 28A8F126AB240B1C temp: 21.50"),
        ),
        (b"[DEBUG] pin: 4 value: 1", BoardLogLine(BoardLogLevel.DEBUG, "pin: 4 value: 1")),
        (
            b"[DEBUG] REGISTERED io-pin (INPUT_PULLUP) - on pin: 4",
            BoardLogLine(BoardLogLevel.DEBUG, "REGISTERED io-pin (INPUT_PULLUP) - on pin: 4"),
        ),
        (
            b"[DEBUG] Locating devices...Found 2 devices.",
            BoardLogLine(BoardLogLevel.DEBUG, "Locating devices...Found 2 devices."),
        ),
        (
            b"[DEBUG] Found device 0 with address: 28A8F126AB240B1C",
            BoardLogLine(BoardLogLevel.DEBUG, "Found device 0 with address: 28A8F126AB240B1C"),
        ),
        (
            b"[DEBUG] Found ghost device at 1 but could not detect address."
            b" Check power and cabling[DEBUG] Found device 0 with address: 28A8F126AB240B1C",
            BoardLogLine(
                BoardLogLevel.DEBUG,
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


def test_temperatures_frame_gives_a_value_per_address() -> None:
    line = b'{"temps":[{"a":"28A8F126AB240B1C","t":21.50},{"a":"28FF4A7C61160398","t":-3}]}'

    assert parse_board_line(line) == TemperaturesFrame(
        (
            TemperatureFrameEntry("28A8F126AB240B1C", 21.5, None),
            TemperatureFrameEntry("28FF4A7C61160398", -3.0, None),
        )
    )


def test_temperatures_entry_with_an_error_code_has_no_value() -> None:
    line = b'{"temps":[{"a":"28A8F126AB240B1C","t":null,"e":"read_failed"}]}'

    assert parse_board_line(line) == TemperaturesFrame(
        (TemperatureFrameEntry("28A8F126AB240B1C", None, "read_failed"),)
    )


def test_unknown_error_code_is_passed_on_unchanged() -> None:
    line = b'{"temps":[{"a":"28A8F126AB240B1C","t":null,"e":"crc_error"}]}'

    assert parse_board_line(line) == TemperaturesFrame(
        (TemperatureFrameEntry("28A8F126AB240B1C", None, "crc_error"),)
    )


def test_empty_temperatures_frame_is_accepted() -> None:
    assert parse_board_line(b'{"temps":[]}') == TemperaturesFrame(())


@pytest.mark.parametrize(
    "line",
    [
        pytest.param(b'{"temps":[5]}', id="entry-not-an-object"),
        pytest.param(b'{"temps":[{"a":"28a8f126ab240b1c","t":1.0}]}', id="lowercase-address"),
        pytest.param(b'{"temps":[{"a":"28A8","t":1.0}]}', id="short-address"),
        pytest.param(
            b'{"temps":[{"a":"28A8F126AB240B1C\\n","t":1.0}]}', id="address-with-trailing-newline"
        ),
        pytest.param(b'{"temps":[{"a":5,"t":1.0}]}', id="address-not-a-string"),
        pytest.param(b'{"temps":[{"t":1.0}]}', id="missing-address"),
        pytest.param(b'{"temps":[{"a":"28A8F126AB240B1C"}]}', id="missing-value"),
        pytest.param(
            b'{"temps":[{"a":"28A8F126AB240B1C","t":1.0},{"a":"28A8F126AB240B1C","t":2.0}]}',
            id="repeated-address",
        ),
        pytest.param(b'{"temps":[{"a":"28A8F126AB240B1C","t":"21.5"}]}', id="value-as-string"),
        pytest.param(b'{"temps":[{"a":"28A8F126AB240B1C","t":true}]}', id="value-as-boolean"),
        pytest.param(b'{"temps":[{"a":"28A8F126AB240B1C","t":NaN}]}', id="value-nan"),
        pytest.param(b'{"temps":[{"a":"28A8F126AB240B1C","t":Infinity}]}', id="value-infinite"),
        pytest.param(
            b'{"temps":[{"a":"28A8F126AB240B1C","t":1' + b"0" * 400 + b"}]}",
            id="value-huge-integer",
        ),
        pytest.param(b'{"temps":[{"a":"28A8F126AB240B1C","t":1000.0}]}', id="value-too-large"),
        pytest.param(b'{"temps":[{"a":"28A8F126AB240B1C","t":999.995}]}', id="value-rounds-up"),
        pytest.param(b'{"temps":[{"a":"28A8F126AB240B1C","t":-1000}]}', id="value-too-small"),
        pytest.param(b'{"temps":[{"a":"28A8F126AB240B1C","t":null}]}', id="null-without-code"),
        pytest.param(
            b'{"temps":[{"a":"28A8F126AB240B1C","t":1.0,"e":"read_failed"}]}',
            id="code-with-value",
        ),
        pytest.param(b'{"temps":[{"a":"28A8F126AB240B1C","t":null,"e":""}]}', id="empty-code"),
        pytest.param(
            b'{"temps":[{"a":"28A8F126AB240B1C","t":null,"e":5}]}', id="code-not-a-string"
        ),
        pytest.param(b'{"temps":[{"a":"28A8F126AB240B1C","t":1.0,"x":1}]}', id="unknown-key"),
    ],
)
def test_malformed_temperature_entries_reject_the_whole_frame(line: bytes) -> None:
    assert parse_board_line(line) is None


def test_largest_storable_temperature_is_accepted() -> None:
    line = b'{"temps":[{"a":"28A8F126AB240B1C","t":-999.99}]}'

    assert parse_board_line(line) == TemperaturesFrame(
        (TemperatureFrameEntry("28A8F126AB240B1C", -999.99, None),)
    )


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
    assert parse_board_line(temperatures) == TemperaturesFrame(
        (TemperatureFrameEntry("28A8F126AB240B1C", 21.5, None),)
    )


def test_every_simulator_banner_line_is_a_log_line() -> None:
    lines = banner_lines(ONE_TANK_WITH_SENSORS.board)

    parsed = [parse_board_line(line.encode("ascii")) for line in lines]

    assert all(isinstance(item, BoardLogLine) for item in parsed)
