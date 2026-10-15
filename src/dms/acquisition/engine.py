import queue
import threading
from collections.abc import Mapping

import structlog

from dms.acquisition.clock import NS_PER_S
from dms.domain.records import MeterRecord
from dms.domain.silo import Silo
from dms.logs import events
from dms.messages import EngineMessage, MeterReading, SignalStates, Tick

GET_TIMEOUT_S = 0.5


class Engine:
    def __init__(
        self,
        *,
        in_queue: queue.Queue[EngineMessage],
        out_queue: queue.Queue[MeterRecord],
        silos_by_meter: Mapping[str, Silo],
        stop_event: threading.Event,
    ) -> None:
        self._in_queue = in_queue
        self._out_queue = out_queue
        self._silos_by_meter = silos_by_meter
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
        elif isinstance(message, SignalStates):
            for silo in self._silos_by_meter.values():
                for change in silo.on_signals(message):
                    structlog.get_logger().info(
                        events.SIGNAL_CHANGED,
                        tank_id=change.tank_id,
                        signal=change.signal,
                        active=change.active,
                        previous=change.previous,
                    )
        elif isinstance(message, Tick):
            for silo in self._silos_by_meter.values():
                stale_since_before_ns = silo.stale_since_mono_ns
                record = silo.on_tick(message)
                self._log_freshness_change(silo, stale_since_before_ns, message.mono_ns)
                if record is not None:
                    self._out_queue.put(record)

    def _log_freshness_change(
        self, silo: Silo, stale_since_before_ns: int | None, tick_mono_ns: int
    ) -> None:
        stale_since_now_ns = silo.stale_since_mono_ns
        if stale_since_before_ns is None and stale_since_now_ns is not None:
            structlog.get_logger().warning(events.SILO_READING_STALE, silo_id=silo.silo_id)
        elif stale_since_before_ns is not None and stale_since_now_ns is None:
            structlog.get_logger().info(
                events.SILO_READING_STALE_ENDED,
                silo_id=silo.silo_id,
                duration_s=(tick_mono_ns - stale_since_before_ns) / NS_PER_S,
            )
