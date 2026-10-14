from dms.domain.reading_cache import ReadingCache
from dms.domain.records import MeterRecord
from dms.domain.tank import SignalChange, Tank
from dms.messages import MeterReading, SignalStates, Tick


class Silo:
    def __init__(
        self, silo_id: int, max_reading_age_ns: int, tank_ids: tuple[int, ...] = ()
    ) -> None:
        self.silo_id = silo_id
        self._tanks = {tank_id: Tank(tank_id) for tank_id in tank_ids}
        self._max_reading_age_ns = max_reading_age_ns
        self._cache = ReadingCache()
        self._last_emitted_mono_ns: int | None = None
        self._stale_since_mono_ns: int | None = None

    @property
    def stale_since_mono_ns(self) -> int | None:
        return self._stale_since_mono_ns

    def on_reading(self, reading: MeterReading) -> None:
        self._cache.add(reading)

    def on_signals(self, states: SignalStates) -> list[SignalChange]:
        changes: list[SignalChange] = []
        for signals in states.tanks:
            tank = self._tanks.get(signals.tank_id)
            if tank is not None:
                changes.extend(tank.on_signals(signals))
        return changes

    def on_tick(self, tick: Tick) -> MeterRecord | None:
        reading = self._cache.advance_to(tick.mono_ns)
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
