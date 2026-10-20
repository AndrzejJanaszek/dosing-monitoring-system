import queue

import structlog

from dms.acquisition.meters.parsing import FrameParser, OutOfRange
from dms.acquisition.serial.adapter import FrameOutcome
from dms.logs import events
from dms.messages import EngineMessage, MeterReading

logger = structlog.get_logger()


class MeterFrameHandler:
    def __init__(
        self,
        *,
        meter_id: str,
        port_name: str,
        parser: FrameParser,
        out_queue: queue.Queue[EngineMessage],
    ) -> None:
        self._meter_id = meter_id
        self._parser = parser
        self._out_queue = out_queue
        self._logger = logger.bind(device_id=meter_id, port=port_name)
        self._out_of_range: OutOfRange | None = None

    def handle(self, frame: bytes, wall_ns: int, mono_ns: int) -> FrameOutcome:
        parsed = self._parser(frame)
        if parsed is None:
            return FrameOutcome.REJECTED
        if isinstance(parsed, OutOfRange):
            self._note_out_of_range(parsed)
        else:
            self._publish(
                MeterReading(
                    meter_id=self._meter_id, value_kg=parsed, wall_ns=wall_ns, mono_ns=mono_ns
                )
            )
        return FrameOutcome.ACCEPTED

    def _publish(self, reading: MeterReading) -> None:
        if self._out_of_range is not None:
            self._logger.info(events.METER_BACK_IN_RANGE, status=self._out_of_range.value)
            self._out_of_range = None
        self._out_queue.put(reading)

    def _note_out_of_range(self, status: OutOfRange) -> None:
        if status != self._out_of_range:
            self._logger.warning(events.METER_OUT_OF_RANGE, status=status.value)
            self._out_of_range = status
