import json
from collections.abc import Callable, Mapping

from dms.acquisition.meters.dgtp import encode_dgtp_frame
from dms.config.models import MeterFormat
from dms.simulator.layout import PlantLayout, SignalBoard
from dms.simulator.timeline import MeterSample, PinsSample, Sample, TemperaturesSample

METER_ENCODERS: Mapping[MeterFormat, Callable[[int], bytes]] = {"dgtp": encode_dgtp_frame}

BOARD_FRAME_END = b"\r\n"
BOARD_JSON_SEPARATORS = (",", ":")
TEMPERATURE_FORMAT = ".2f"


def encode_pins_frame(levels: tuple[tuple[int, int], ...]) -> bytes:
    payload = {"pins": {str(pin): level for pin, level in levels}}
    return json.dumps(payload, separators=BOARD_JSON_SEPARATORS).encode("ascii") + BOARD_FRAME_END


def encode_temperatures_frame(readings: tuple[tuple[str, float], ...]) -> bytes:
    items = ",".join(
        f'{{"a":{json.dumps(address)},"t":{temperature_c:{TEMPERATURE_FORMAT}}}}'
        for address, temperature_c in readings
    )
    return f'{{"temps":[{items}]}}'.encode("ascii") + BOARD_FRAME_END


def banner_lines(board: SignalBoard) -> tuple[str, ...]:
    if board.banner is not None:
        return board.banner
    return (
        f"[DEBUG] Locating devices...Found {len(board.sensors)} devices.",
        *(
            f"[DEBUG] Found device {index} with address: {sensor.address}"
            for index, sensor in enumerate(board.sensors)
        ),
        *(f"[DEBUG] REGISTERED io-pin (INPUT_PULLUP) - on pin: {pin}" for pin in board.pins),
    )


def encode_sample(sample: Sample, layout: PlantLayout) -> tuple[str, bytes]:
    match sample:
        case MeterSample():
            meter_format = layout.silo_of_meter(sample.meter_id).meter.format
            return sample.meter_id, METER_ENCODERS[meter_format](sample.value_kg)
        case PinsSample():
            return sample.board_id, encode_pins_frame(sample.levels)
        case TemperaturesSample():
            return sample.board_id, encode_temperatures_frame(sample.readings)
