import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from dms.config.models import MAX_TEMPERATURE_ABS_C, PIN_LEVELS, SENSOR_ADDRESS_PATTERN

LOG_PREFIX_OPEN = "["
LOG_PREFIX_CLOSE = "]"
LOG_MESSAGE_SEPARATORS = ": "
PINS_KEY = "pins"
TEMPERATURES_KEY = "temps"
ADDRESS_KEY = "a"
TEMPERATURE_KEY = "t"
ERROR_KEY = "e"
ENTRY_KEYS = frozenset({ADDRESS_KEY, TEMPERATURE_KEY, ERROR_KEY})
REQUIRED_ENTRY_KEYS = frozenset({ADDRESS_KEY, TEMPERATURE_KEY})


class BoardLogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class PinLevels:
    levels: Mapping[int, int]


@dataclass(frozen=True, slots=True)
class TemperatureFrameEntry:
    address: str
    value_c: float | None
    error_code: str | None


@dataclass(frozen=True, slots=True)
class TemperaturesFrame:
    entries: tuple[TemperatureFrameEntry, ...]


@dataclass(frozen=True, slots=True)
class BoardLogLine:
    level: BoardLogLevel
    message: str


type BoardFrame = PinLevels | TemperaturesFrame | BoardLogLine


def parse_board_line(frame: bytes) -> BoardFrame | None:
    try:
        line = frame.decode("ascii")
    except UnicodeDecodeError:
        return None
    log_line = _parse_log_line(line)
    return log_line if log_line is not None else _parse_json_line(line)


def _parse_json_line(line: str) -> PinLevels | TemperaturesFrame | None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or len(payload) != 1:
        return None
    if TEMPERATURES_KEY in payload:
        return _parse_temperatures(payload[TEMPERATURES_KEY])
    return _parse_pin_levels(payload[PINS_KEY]) if PINS_KEY in payload else None


def _parse_log_line(line: str) -> BoardLogLine | None:
    for level in BoardLogLevel:
        prefix = f"{LOG_PREFIX_OPEN}{level}{LOG_PREFIX_CLOSE}"
        if line.startswith(prefix):
            return BoardLogLine(level, line.removeprefix(prefix).lstrip(LOG_MESSAGE_SEPARATORS))
    return None


def _parse_pin_levels(raw_levels: object) -> PinLevels | None:
    if not isinstance(raw_levels, dict):
        return None
    levels: dict[int, int] = {}
    for key, value in raw_levels.items():
        if not (key.isascii() and key.isdecimal()):
            return None
        if not isinstance(value, int) or isinstance(value, bool) or value not in PIN_LEVELS:
            return None
        levels[int(key)] = value
    return PinLevels(levels)


def _parse_temperatures(raw_entries: object) -> TemperaturesFrame | None:
    if not isinstance(raw_entries, list):
        return None
    entries: list[TemperatureFrameEntry] = []
    for raw_entry in raw_entries:
        entry = _parse_temperature_entry(raw_entry)
        if entry is None or any(entry.address == other.address for other in entries):
            return None
        entries.append(entry)
    return TemperaturesFrame(tuple(entries))


def _parse_temperature_entry(raw_entry: object) -> TemperatureFrameEntry | None:
    if not isinstance(raw_entry, dict):
        return None
    if not REQUIRED_ENTRY_KEYS <= raw_entry.keys() <= ENTRY_KEYS:
        return None
    address = raw_entry[ADDRESS_KEY]
    if not isinstance(address, str) or SENSOR_ADDRESS_PATTERN.fullmatch(address) is None:
        return None

    raw_value = raw_entry[TEMPERATURE_KEY]
    error_code = raw_entry.get(ERROR_KEY)
    if raw_value is None and isinstance(error_code, str) and error_code:
        return TemperatureFrameEntry(address, None, error_code)
    if ERROR_KEY not in raw_entry and _is_storable_temperature(raw_value):
        return TemperatureFrameEntry(address, float(raw_value), None)
    return None


def _is_storable_temperature(raw_value: object) -> bool:
    if isinstance(raw_value, bool) or not isinstance(raw_value, int | float):
        return False
    return math.isfinite(raw_value) and abs(raw_value) <= MAX_TEMPERATURE_ABS_C
