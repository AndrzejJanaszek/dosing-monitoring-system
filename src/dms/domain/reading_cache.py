from collections import deque

from dms.messages import MeterReading

READING_WINDOW_NS = 60 * 1_000_000_000


class ReadingCache:
    def __init__(self, window_ns: int = READING_WINDOW_NS) -> None:
        self._window_ns = window_ns
        self._readings: deque[MeterReading] = deque()

    def add(self, reading: MeterReading) -> None:
        self._readings.append(reading)
        oldest_kept_ns = reading.mono_ns - self._window_ns
        while self._readings and self._readings[0].mono_ns < oldest_kept_ns:
            self._readings.popleft()

    def at_or_before(self, mono_ns: int) -> MeterReading | None:
        for reading in reversed(self._readings):
            if reading.mono_ns <= mono_ns:
                return reading
        return None
