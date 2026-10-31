import queue
import threading
from collections.abc import Mapping, Sequence

import structlog

from dms.acquisition.temperature_logging import log_temperature_notice
from dms.domain.collisions import RuleViolation
from dms.domain.events import EventStatus, StartedEvent, StartQuality
from dms.domain.records import (
    EventRecord,
    MeterRecord,
    TemperatureRecord,
    UnknownSensorRecord,
    WriterRecord,
)
from dms.domain.silo import Silo
from dms.domain.tank import SignalChange
from dms.domain.temperatures import TemperatureOutput, TemperatureSensors
from dms.logs import events
from dms.messages import EngineMessage, MeterReading, SignalStates, TemperatureReadings, Tick
from dms.units import NS_PER_S

GET_TIMEOUT_S = 0.5

type SiloOutput = SignalChange | RuleViolation | MeterRecord | StartedEvent | EventRecord

logger = structlog.get_logger()


class Engine:
    def __init__(
        self,
        *,
        in_queue: queue.Queue[EngineMessage],
        out_queue: queue.Queue[WriterRecord],
        silos_by_meter: Mapping[str, Silo],
        stop_event: threading.Event,
        temperatures: TemperatureSensors | None = None,
    ) -> None:
        self._in_queue = in_queue
        self._out_queue = out_queue
        self._silos_by_meter = silos_by_meter
        self._stop_event = stop_event
        self._temperatures = temperatures

    def run(self) -> None:
        try:
            while not self._stop_event.is_set():
                self.step()
            self._drain()
            self._close_open_events()
        except Exception as error:
            logger.critical(events.ENGINE_FATAL, error=str(error), exc_info=True)
            raise

    def step(self) -> None:
        try:
            message = self._in_queue.get(timeout=GET_TIMEOUT_S)
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
        elif isinstance(message, TemperatureReadings):
            if self._temperatures is not None:
                self._route_temperatures(self._temperatures.on_readings(message))
        elif isinstance(message, Tick):
            self._handle_tick(message)

    def _handle_tick(self, message: Tick) -> None:
        if self._temperatures is not None:
            self._route_temperatures(self._temperatures.on_tick(message))
        for silo in self._silos_by_meter.values():
            stale_since_before_ns = silo.stale_since_mono_ns
            signals_stale_since_before_ns = silo.signals_stale_since_mono_ns
            tick_outputs = silo.on_tick(message)
            self._log_freshness_change(silo, stale_since_before_ns, message.mono_ns)
            self._log_signals_freshness_change(
                silo, signals_stale_since_before_ns, message.mono_ns
            )
            self._route(tick_outputs)

    def _drain(self) -> None:
        while True:
            try:
                message = self._in_queue.get_nowait()
            except queue.Empty:
                return
            self.handle(message)

    def _close_open_events(self) -> None:
        for silo in self._silos_by_meter.values():
            self._route(silo.on_shutdown())

    def _route(self, outputs: Sequence[SiloOutput]) -> None:
        for output in outputs:
            if isinstance(output, SignalChange):
                self._log_signal_change(output)
                continue
            if isinstance(output, RuleViolation):
                self._log_rule_violation(output)
                continue
            if isinstance(output, StartedEvent):
                self._log_started(output)
            elif isinstance(output, EventRecord):
                self._log_closed(output)
            self._out_queue.put(output)

    def _route_temperatures(self, outputs: Sequence[TemperatureOutput]) -> None:
        for output in outputs:
            if isinstance(output, TemperatureRecord | UnknownSensorRecord):
                self._out_queue.put(output)
            else:
                log_temperature_notice(output)

    def _log_signal_change(self, change: SignalChange) -> None:
        logger.info(
            events.SIGNAL_CHANGED,
            tank_id=change.tank_id,
            signal=change.signal,
            active=change.active,
            previous=change.previous,
        )

    def _log_rule_violation(self, violation: RuleViolation) -> None:
        logger.warning(
            events.SILO_RULE_VIOLATION,
            silo_id=violation.silo_id,
            type=violation.kind,
            tank_id=violation.tank_id,
            event_id=str(violation.event_id),
            other_tank_id=violation.other_tank_id,
            other_event_id=str(violation.other_event_id),
        )

    def _log_started(self, event: StartedEvent) -> None:
        fields = {
            "event_id": str(event.event_id),
            "tank_id": event.tank_id,
            "type": event.kind,
            "start_value_kg": event.start_value_kg,
            "start_quality": event.start_quality,
        }
        if event.start_quality is StartQuality.UNKNOWN:
            logger.warning(events.EVENT_ORPHANED, **fields)
        else:
            logger.info(events.EVENT_STARTED, **fields)

    def _log_closed(self, record: EventRecord) -> None:
        event = record.event
        fields = {
            "event_id": str(event.event_id),
            "tank_id": event.tank_id,
            "type": event.kind,
            "start_value_kg": event.start_value_kg,
            "end_value_kg": event.end_value_kg,
            "duration_s": None if event.duration_ns is None else event.duration_ns / NS_PER_S,
            "collision": record.collision,
            "rule_violation": record.rule_violation,
        }
        if event.status is EventStatus.INCOMPLETE:
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
            logger.warning(events.SILO_SIGNALS_STALE, silo_id=silo.silo_id)
        elif stale_since_before_ns is not None and stale_since_now_ns is None:
            logger.info(
                events.SILO_SIGNALS_STALE_ENDED,
                silo_id=silo.silo_id,
                duration_s=(mono_ns - stale_since_before_ns) / NS_PER_S,
            )

    def _log_freshness_change(
        self, silo: Silo, stale_since_before_ns: int | None, tick_mono_ns: int
    ) -> None:
        stale_since_now_ns = silo.stale_since_mono_ns
        if stale_since_before_ns is None and stale_since_now_ns is not None:
            logger.warning(events.SILO_READING_STALE, silo_id=silo.silo_id)
        elif stale_since_before_ns is not None and stale_since_now_ns is None:
            logger.info(
                events.SILO_READING_STALE_ENDED,
                silo_id=silo.silo_id,
                duration_s=(tick_mono_ns - stale_since_before_ns) / NS_PER_S,
            )
