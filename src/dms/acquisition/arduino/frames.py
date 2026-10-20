import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from dms.config.models import PIN_LEVELS

LOG_PREFIX_OPEN = "["
LOG_PREFIX_CLOSE = "]"
LOG_MESSAGE_SEPARATORS = ": "
PINS_KEY = "pins"
TEMPERATURES_KEY = "temps"


class BoardLogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class PinLevels:
    levels: Mapping[int, int]


@dataclass(frozen=True, slots=True)
class TemperaturesFrame:
    pass


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
        return TemperaturesFrame() if isinstance(payload[TEMPERATURES_KEY], list) else None
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
