import logging
import queue

import structlog

from dms.acquisition.arduino.frames import (
    BoardLogLevel,
    BoardLogLine,
    PinLevels,
    TemperaturesFrame,
    parse_board_line,
)
from dms.acquisition.arduino.mapping import SignalMapper
from dms.acquisition.serial.adapter import FrameOutcome
from dms.logs import events
from dms.messages import EngineMessage, SignalStates

LOG_LEVELS: dict[BoardLogLevel, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


class ArduinoFrameHandler:
    def __init__(
        self,
        *,
        board_id: str,
        port_name: str,
        mapper: SignalMapper,
        out_queue: queue.Queue[EngineMessage],
    ) -> None:
        self._mapper = mapper
        self._out_queue = out_queue
        self._logger = structlog.get_logger().bind(device_id=board_id, port=port_name)
        self._missing_pins: frozenset[int] = frozenset()

    def handle(self, frame: bytes, wall_ns: int, mono_ns: int) -> FrameOutcome:
        parsed = parse_board_line(frame)
        if parsed is None:
            return FrameOutcome.REJECTED
        if isinstance(parsed, BoardLogLine):
            self._log_board_line(parsed)
            return FrameOutcome.IGNORED
        if isinstance(parsed, TemperaturesFrame):
            return FrameOutcome.ACCEPTED
        return self._handle_pins(parsed, wall_ns, mono_ns)

    def _log_board_line(self, line: BoardLogLine) -> None:
        self._logger.log(LOG_LEVELS[line.level], events.ARDUINO_LOG, message=line.message)

    def _handle_pins(self, parsed: PinLevels, wall_ns: int, mono_ns: int) -> FrameOutcome:
        missing = self._mapper.missing_pins(parsed.levels)
        if missing:
            if missing != self._missing_pins:
                self._logger.warning(events.ARDUINO_PINS_MISSING, pins=sorted(missing))
            self._missing_pins = missing
            return FrameOutcome.IGNORED
        if self._missing_pins:
            self._logger.info(events.ARDUINO_PINS_RESTORED)
            self._missing_pins = frozenset()
        self._out_queue.put(SignalStates(self._mapper.signals(parsed.levels), wall_ns, mono_ns))
        return FrameOutcome.ACCEPTED
