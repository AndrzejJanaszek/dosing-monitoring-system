import bisect
from operator import attrgetter

from dms.messages import MeterReading

MONO_NS = attrgetter("mono_ns")


class ReadingCache:
    def __init__(self, window_ns: int) -> None:
        self._window_ns = window_ns
        self._readings: list[MeterReading] = []

    def add(self, reading: MeterReading) -> None:
        bisect.insort_right(self._readings, reading, key=MONO_NS)
        oldest_kept_ns = self._readings[-1].mono_ns - self._window_ns
        expired_count = bisect.bisect_left(self._readings, oldest_kept_ns, key=MONO_NS)
        del self._readings[:expired_count]

    def at_or_before(self, mono_ns: int) -> MeterReading | None:
        after_count = bisect.bisect_right(self._readings, mono_ns, key=MONO_NS)
        if after_count == 0:
            return None
        return self._readings[after_count - 1]

    def __len__(self) -> int:
        return len(self._readings)
