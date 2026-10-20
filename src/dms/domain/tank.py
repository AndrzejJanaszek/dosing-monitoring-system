from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum, auto
from uuid import UUID

from dms.domain.events import ClosedEvent, EndQuality, EventKind, StartedEvent, StartQuality
from dms.messages import TankSignals


@dataclass(frozen=True, slots=True, kw_only=True)
class SignalChange:
    tank_id: int
    signal: EventKind
    active: bool
    previous: bool | None


type TankOutput = SignalChange | StartedEvent | ClosedEvent


class _Phase(Enum):
    UNKNOWN = auto()
    IDLE = auto()
    ORPHANED = auto()
    IN_PROGRESS = auto()


@dataclass(frozen=True, slots=True, kw_only=True)
class _OpenEvent:
    event_id: UUID
    start_wall_ns: int
    start_mono_ns: int | None
    start_value_kg: int | None
    start_quality: StartQuality


class SignalEventTracker:
    def __init__(
        self,
        tank_id: int,
        kind: EventKind,
        new_event_id: Callable[[], UUID],
        unknown_since_wall_ns: int,
    ) -> None:
        self._tank_id = tank_id
        self._kind: EventKind = kind
        self._new_event_id = new_event_id
        self._unknown_since_wall_ns = unknown_since_wall_ns
        self._phase = _Phase.UNKNOWN
        self._open: _OpenEvent | None = None

    def on_state(
        self, *, active: bool, wall_ns: int, mono_ns: int, value_kg: int | None
    ) -> Sequence[StartedEvent | ClosedEvent]:
        if self._phase is _Phase.UNKNOWN:
            return self._leave_unknown(active=active)
        if self._phase is _Phase.IDLE:
            return [self._start(wall_ns, mono_ns, value_kg)] if active else []
        if active:
            return []
        return self._close(wall_ns, mono_ns, value_kg, _end_quality(value_kg))

    def close_open(
        self, last_fresh_wall_ns: int, last_fresh_mono_ns: int, end_quality: EndQuality
    ) -> list[ClosedEvent]:
        closed = self._close(last_fresh_wall_ns, last_fresh_mono_ns, None, end_quality)
        self._phase = _Phase.UNKNOWN
        self._unknown_since_wall_ns = last_fresh_wall_ns
        return closed

    def _leave_unknown(self, *, active: bool) -> Sequence[StartedEvent | ClosedEvent]:
        if not active:
            self._phase = _Phase.IDLE
            return []
        self._phase = _Phase.ORPHANED
        self._open = _OpenEvent(
            event_id=self._new_event_id(),
            start_wall_ns=self._unknown_since_wall_ns,
            start_mono_ns=None,
            start_value_kg=None,
            start_quality=StartQuality.UNKNOWN,
        )
        return [self._started(self._open)]

    def _start(self, wall_ns: int, mono_ns: int, value_kg: int | None) -> StartedEvent:
        self._phase = _Phase.IN_PROGRESS
        start_quality = StartQuality.STALE_READING if value_kg is None else StartQuality.FRESH
        self._open = _OpenEvent(
            event_id=self._new_event_id(),
            start_wall_ns=wall_ns,
            start_mono_ns=mono_ns,
            start_value_kg=value_kg,
            start_quality=start_quality,
        )
        return self._started(self._open)

    def _started(self, opened: _OpenEvent) -> StartedEvent:
        return StartedEvent(
            event_id=opened.event_id,
            tank_id=self._tank_id,
            kind=self._kind,
            start_wall_ns=opened.start_wall_ns,
            start_value_kg=opened.start_value_kg,
            start_quality=opened.start_quality,
        )

    def _close(
        self,
        end_wall_ns: int,
        end_mono_ns: int,
        end_value_kg: int | None,
        end_quality: EndQuality,
    ) -> list[ClosedEvent]:
        opened = self._open
        self._open = None
        self._phase = _Phase.IDLE
        if opened is None:
            return []
        duration_ns = None if opened.start_mono_ns is None else end_mono_ns - opened.start_mono_ns
        return [
            ClosedEvent(
                event_id=opened.event_id,
                tank_id=self._tank_id,
                kind=self._kind,
                start_wall_ns=opened.start_wall_ns,
                start_value_kg=opened.start_value_kg,
                end_wall_ns=end_wall_ns,
                end_value_kg=end_value_kg,
                duration_ns=duration_ns,
                start_quality=opened.start_quality,
                end_quality=end_quality,
            )
        ]


def _end_quality(value_kg: int | None) -> EndQuality:
    return EndQuality.STALE_READING if value_kg is None else EndQuality.FRESH


class Tank:
    def __init__(
        self, tank_id: int, new_event_id: Callable[[], UUID], unknown_since_wall_ns: int
    ) -> None:
        self.tank_id = tank_id
        self._dispense: bool | None = None
        self._refill: bool | None = None
        self._dispense_events = SignalEventTracker(
            tank_id, EventKind.DISPENSE, new_event_id, unknown_since_wall_ns
        )
        self._refill_events = SignalEventTracker(
            tank_id, EventKind.REFILL, new_event_id, unknown_since_wall_ns
        )

    def on_signals(
        self, signals: TankSignals, wall_ns: int, mono_ns: int, value_kg: int | None
    ) -> list[TankOutput]:
        outputs: list[TankOutput] = []
        if signals.dispense != self._dispense:
            outputs.append(
                SignalChange(
                    tank_id=self.tank_id,
                    signal=EventKind.DISPENSE,
                    active=signals.dispense,
                    previous=self._dispense,
                )
            )
            self._dispense = signals.dispense
        if signals.refill != self._refill:
            outputs.append(
                SignalChange(
                    tank_id=self.tank_id,
                    signal=EventKind.REFILL,
                    active=signals.refill,
                    previous=self._refill,
                )
            )
            self._refill = signals.refill
        outputs.extend(
            self._dispense_events.on_state(
                active=signals.dispense, wall_ns=wall_ns, mono_ns=mono_ns, value_kg=value_kg
            )
        )
        outputs.extend(
            self._refill_events.on_state(
                active=signals.refill, wall_ns=wall_ns, mono_ns=mono_ns, value_kg=value_kg
            )
        )
        return outputs

    def on_signals_lost(
        self, last_fresh_wall_ns: int, last_fresh_mono_ns: int
    ) -> list[ClosedEvent]:
        self._dispense = None
        self._refill = None
        return self._close_open_events(
            last_fresh_wall_ns, last_fresh_mono_ns, EndQuality.SIGNAL_LOST
        )

    def on_shutdown(self, last_fresh_wall_ns: int, last_fresh_mono_ns: int) -> list[ClosedEvent]:
        return self._close_open_events(
            last_fresh_wall_ns, last_fresh_mono_ns, EndQuality.SERVICE_STOPPED
        )

    def _close_open_events(
        self, last_fresh_wall_ns: int, last_fresh_mono_ns: int, end_quality: EndQuality
    ) -> list[ClosedEvent]:
        return [
            *self._dispense_events.close_open(last_fresh_wall_ns, last_fresh_mono_ns, end_quality),
            *self._refill_events.close_open(last_fresh_wall_ns, last_fresh_mono_ns, end_quality),
        ]
