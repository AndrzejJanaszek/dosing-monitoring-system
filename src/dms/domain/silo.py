from collections.abc import Callable
from uuid import UUID

from dms.domain.events import ClosedEvent
from dms.domain.reading_cache import ReadingCache
from dms.domain.records import MeterRecord
from dms.domain.tank import Tank, TankOutput
from dms.messages import MeterReading, SignalStates, Tick


class Silo:
    def __init__(
        self,
        silo_id: int,
        *,
        max_reading_age_ns: int,
        max_signal_age_ns: int,
        reading_cache_window_ns: int,
        tank_ids: tuple[int, ...],
        new_event_id: Callable[[], UUID],
        started_wall_ns: int,
        started_mono_ns: int,
    ) -> None:
        self.silo_id = silo_id
        self._tanks = {
            tank_id: Tank(tank_id, new_event_id, started_wall_ns) for tank_id in tank_ids
        }
        self._max_reading_age_ns = max_reading_age_ns
        self._max_signal_age_ns = max_signal_age_ns
        self._cache = ReadingCache(reading_cache_window_ns)
        self._last_emitted_mono_ns: int | None = None
        self._stale_since_mono_ns: int | None = None
        self._last_signals_wall_ns = started_wall_ns
        self._last_signals_mono_ns = started_mono_ns
        self._signals_stale_since_mono_ns: int | None = None

    @property
    def stale_since_mono_ns(self) -> int | None:
        return self._stale_since_mono_ns

    @property
    def signals_stale_since_mono_ns(self) -> int | None:
        return self._signals_stale_since_mono_ns

    def on_reading(self, reading: MeterReading) -> None:
        self._cache.add(reading)

    def on_signals(self, states: SignalStates) -> list[TankOutput]:
        value_kg = self._fresh_value_at(states.mono_ns)
        self._last_signals_wall_ns = states.wall_ns
        self._last_signals_mono_ns = states.mono_ns
        self._signals_stale_since_mono_ns = None
        outputs: list[TankOutput] = []
        for signals in states.tanks:
            tank = self._tanks.get(signals.tank_id)
            if tank is not None:
                outputs.extend(tank.on_signals(signals, states.wall_ns, states.mono_ns, value_kg))
        return outputs

    def on_tick(self, tick: Tick) -> list[MeterRecord | ClosedEvent]:
        records: list[MeterRecord | ClosedEvent] = []
        record = self._cyclic_record(tick)
        if record is not None:
            records.append(record)
        records.extend(self._events_closed_by_lost_signals(tick))
        return records

    def _fresh_value_at(self, mono_ns: int) -> int | None:
        reading = self._cache.at_or_before(mono_ns)
        if reading is None or mono_ns - reading.mono_ns > self._max_reading_age_ns:
            return None
        return reading.value_kg

    def _cyclic_record(self, tick: Tick) -> MeterRecord | None:
        reading = self._cache.at_or_before(tick.mono_ns)
        if reading is None:
            return None
        if tick.mono_ns - reading.mono_ns > self._max_reading_age_ns:
            if self._stale_since_mono_ns is None:
                self._stale_since_mono_ns = reading.mono_ns + self._max_reading_age_ns
            return None
        self._stale_since_mono_ns = None
        if reading.mono_ns == self._last_emitted_mono_ns:
            return None
        self._last_emitted_mono_ns = reading.mono_ns
        return MeterRecord(self.silo_id, reading.wall_ns, reading.value_kg)

    def _events_closed_by_lost_signals(self, tick: Tick) -> list[ClosedEvent]:
        if not self._tanks or self._signals_stale_since_mono_ns is not None:
            return []
        if tick.mono_ns - self._last_signals_mono_ns <= self._max_signal_age_ns:
            return []
        self._signals_stale_since_mono_ns = self._last_signals_mono_ns + self._max_signal_age_ns
        closed: list[ClosedEvent] = []
        for tank in self._tanks.values():
            closed.extend(
                tank.on_signals_lost(self._last_signals_wall_ns, self._last_signals_mono_ns)
            )
        return closed
