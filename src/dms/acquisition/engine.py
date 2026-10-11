import queue
import threading
from collections.abc import Mapping, Sequence

import structlog

from dms.domain.records import MeterRecord
from dms.domain.silo import Silo
from dms.logs import events
from dms.messages import EngineMessage, MeterReading, Tick

GET_TIMEOUT_S = 0.5


class Engine:
    def __init__(
        self,
        *,
        in_queue: queue.Queue[EngineMessage],
        out_queue: queue.Queue[MeterRecord],
        silos_by_meter: Mapping[str, Silo],
        silos: Sequence[Silo],
        stop_event: threading.Event,
    ) -> None:
        self._in_queue = in_queue
        self._out_queue = out_queue
        self._silos_by_meter = silos_by_meter
        self._silos = silos
        self._stop_event = stop_event

    def run(self) -> None:
        try:
            while not self._stop_event.is_set():
                self.step()
            self._drain()
        except Exception as error:
            structlog.get_logger().critical(events.ENGINE_FATAL, error=repr(error))
            raise

    def step(self) -> None:
        try:
            message = self._in_queue.get(timeout=GET_TIMEOUT_S)
        except queue.Empty:
            return
        self._handle(message)

    def _drain(self) -> None:
        while True:
            try:
                message = self._in_queue.get_nowait()
            except queue.Empty:
                return
            self._handle(message)

    def _handle(self, message: EngineMessage) -> None:
        if isinstance(message, MeterReading):
            silo = self._silos_by_meter.get(message.meter_id)
            if silo is not None:
                silo.on_reading(message)
        elif isinstance(message, Tick):
            for silo in self._silos:
                record = silo.on_tick(message)
                if record is not None:
                    self._out_queue.put(record)
