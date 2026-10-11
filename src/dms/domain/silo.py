from dms.domain.reading_cache import ReadingCache
from dms.domain.records import MeterRecord
from dms.messages import MeterReading, Tick


class Silo:
    def __init__(self, silo_id: int, max_reading_age_ns: int) -> None:
        self.silo_id = silo_id
        self._max_reading_age_ns = max_reading_age_ns
        self._cache = ReadingCache()
        self._last_emitted_mono_ns: int | None = None

    def on_reading(self, reading: MeterReading) -> None:
        self._cache.add(reading)

    def on_tick(self, tick: Tick) -> MeterRecord | None:
        reading = self._cache.at_or_before(tick.mono_ns)
        if reading is None:
            return None
        if tick.mono_ns - reading.mono_ns > self._max_reading_age_ns:
            return None
        if reading.mono_ns == self._last_emitted_mono_ns:
            return None
        self._last_emitted_mono_ns = reading.mono_ns
        return MeterRecord(self.silo_id, reading.wall_ns, reading.value_kg)
