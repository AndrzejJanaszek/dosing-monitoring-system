from dms.acquisition.meters.dgtp import parse_dgtp_frame
from dms.config.models import MeterFormat
from dms.simulator.encoders import (
    METER_ENCODERS,
    banner_lines,
    encode_pins_frame,
    encode_sample,
    encode_temperatures_frame,
)
from dms.simulator.layout import SignalBoard, TemperatureSensor
from dms.simulator.timeline import MeterSample, PinsSample, TemperaturesSample
from tests.unit.simulator.builders import one_tank_layout


def test_pins_frame_matches_firmware_output() -> None:
    levels = ((4, 1), (5, 0), (6, 1), (7, 1), (8, 1), (9, 1))

    assert encode_pins_frame(levels) == b'{"pins":{"4":1,"5":0,"6":1,"7":1,"8":1,"9":1}}\r\n'


def test_temperatures_frame_matches_firmware_output() -> None:
    readings = (("28A8F126AB240B1C", 25.44), ("28FF4A7C61160398", 25.4))

    assert encode_temperatures_frame(readings) == (
        b'{"temps":[{"a":"28A8F126AB240B1C","t":25.44},{"a":"28FF4A7C61160398","t":25.40}]}\r\n'
    )


def test_temperatures_frame_without_sensors() -> None:
    assert encode_temperatures_frame(()) == b'{"temps":[]}\r\n'


def test_meter_frame_round_trips_through_the_parser() -> None:
    frame = METER_ENCODERS[MeterFormat.DGTP](19_980)

    assert parse_dgtp_frame(frame[:-2]) == 19_980


def test_banner_without_sensors() -> None:
    assert banner_lines(SignalBoard()) == (
        "[DEBUG] Locating devices...Found 0 devices.",
        *(f"[DEBUG] REGISTERED io-pin (INPUT_PULLUP) - on pin: {pin}" for pin in range(4, 10)),
    )


def test_banner_with_two_sensors() -> None:
    board = SignalBoard(
        pins=(4, 5),
        sensors=(
            TemperatureSensor(id=1, address="28A8F126AB240B1C", temperature_c=21.5),
            TemperatureSensor(id=2, address="28FF4A7C61160398", temperature_c=22.25),
        ),
    )

    assert banner_lines(board) == (
        "[DEBUG] Locating devices...Found 2 devices.",
        "[DEBUG] Found device 0 with address: 28A8F126AB240B1C",
        "[DEBUG] Found device 1 with address: 28FF4A7C61160398",
        "[DEBUG] REGISTERED io-pin (INPUT_PULLUP) - on pin: 4",
        "[DEBUG] REGISTERED io-pin (INPUT_PULLUP) - on pin: 5",
    )


def test_banner_can_be_overridden() -> None:
    assert banner_lines(SignalBoard(banner=("hello",))) == ("hello",)


def test_encode_sample_returns_device_id_and_bytes() -> None:
    layout = one_tank_layout()

    assert encode_sample(MeterSample(0, "meter-1", 20_000), layout) == (
        "meter-1",
        METER_ENCODERS[MeterFormat.DGTP](20_000),
    )
    assert encode_sample(PinsSample(0, "arduino", ((4, 1),)), layout) == (
        "arduino",
        b'{"pins":{"4":1}}\r\n',
    )
    assert encode_sample(TemperaturesSample(0, "arduino", ()), layout) == (
        "arduino",
        b'{"temps":[]}\r\n',
    )
