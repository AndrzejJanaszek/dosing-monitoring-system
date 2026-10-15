import queue
import threading
from collections.abc import Mapping, Sequence

import structlog

from dms.acquisition.clock import NS_PER_S
from dms.domain.events import ClosedEvent, StartedEvent
from dms.domain.records import MeterRecord, WriterRecord
from dms.domain.silo import Silo
from dms.domain.tank import SignalChange
from dms.logs import events
from dms.messages import EngineMessage, MeterReading, SignalStates, Tick

GET_TIMEOUT_S = 0.5


class Engine:
    def __init__(
        self,
        *,
        in_queue: queue.Queue[EngineMessage],
        out_queue: queue.Queue[WriterRecord],
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
        self.handle(message)

    def _drain(self) -> None:
        while True:
            try:
                message = self._in_queue.get_nowait()
            except queue.Empty:
                return
            self.handle(message)

    def handle(self, message: EngineMessage) -> None:
        if isinstance(message, MeterReading):
            silo = self._silos_by_meter.get(message.meter_id)
            if silo is not None:
                silo.on_reading(message)
        elif isinstance(message, SignalStates):
            for silo in self._silos_by_meter.values():
                signals_stale_since_before_ns = silo.signals_stale_since_mono_ns
                signal_outputs = silo.on_signals(message)
                self._log_signals_freshness_change(
                    silo, signals_stale_since_before_ns, message.mono_ns
                )
                self._route(signal_outputs)
        elif isinstance(message, Tick):
            for silo in self._silos_by_meter.values():
                stale_since_before_ns = silo.stale_since_mono_ns
                signals_stale_since_before_ns = silo.signals_stale_since_mono_ns
                tick_outputs = silo.on_tick(message)
                self._log_freshness_change(silo, stale_since_before_ns, message.mono_ns)
                self._log_signals_freshness_change(
                    silo, signals_stale_since_before_ns, message.mono_ns
                )
                self._route(tick_outputs)

    def _route(
        self, outputs: Sequence[SignalChange | MeterRecord | StartedEvent | ClosedEvent]
    ) -> None:
        for output in outputs:
            if isinstance(output, SignalChange):
                self._log_signal_change(output)
                continue
            if isinstance(output, StartedEvent):
                self._log_started(output)
            elif isinstance(output, ClosedEvent):
                self._log_closed(output)
            self._out_queue.put(output)

    def _log_signal_change(self, change: SignalChange) -> None:
        structlog.get_logger().info(
            events.SIGNAL_CHANGED,
            tank_id=change.tank_id,
            signal=change.signal,
            active=change.active,
            previous=change.previous,
        )

    def _log_started(self, event: StartedEvent) -> None:
        logger = structlog.get_logger()
        fields = {
            "event_id": str(event.event_id),
            "tank_id": event.tank_id,
            "type": event.kind,
            "start_value_kg": event.start_value_kg,
            "start_quality": event.start_quality,
        }
        if event.start_quality == "unknown":
            logger.warning(events.EVENT_ORPHANED, **fields)
        else:
            logger.info(events.EVENT_STARTED, **fields)

    def _log_closed(self, event: ClosedEvent) -> None:
        fields = {
            "event_id": str(event.event_id),
            "tank_id": event.tank_id,
            "type": event.kind,
            "start_value_kg": event.start_value_kg,
            "end_value_kg": event.end_value_kg,
            "duration_s": None if event.duration_ns is None else event.duration_ns / NS_PER_S,
        }
        logger = structlog.get_logger()
        if event.status == "incomplete":
            logger.error(
                events.EVENT_INCOMPLETE,
                start_quality=event.start_quality,
                end_quality=event.end_quality,
                **fields,
            )
            return
        delta_kg = None
        if event.start_value_kg is not None and event.end_value_kg is not None:
            delta_kg = event.end_value_kg - event.start_value_kg
        logger.info(events.EVENT_COMPLETED, delta_kg=delta_kg, **fields)

    def _log_signals_freshness_change(
        self, silo: Silo, stale_since_before_ns: int | None, mono_ns: int
    ) -> None:
        stale_since_now_ns = silo.signals_stale_since_mono_ns
        if stale_since_before_ns is None and stale_since_now_ns is not None:
            structlog.get_logger().warning(events.SILO_SIGNALS_STALE, silo_id=silo.silo_id)
        elif stale_since_before_ns is not None and stale_since_now_ns is None:
            structlog.get_logger().info(
                events.SILO_SIGNALS_STALE_ENDED,
                silo_id=silo.silo_id,
                duration_s=(mono_ns - stale_since_before_ns) / NS_PER_S,
            )

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
