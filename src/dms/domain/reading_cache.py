from collections import deque

from dms.messages import MeterReading


class ReadingCache:
    def __init__(self) -> None:
        self._readings: deque[MeterReading] = deque()

    def add(self, reading: MeterReading) -> None:
        self._readings.append(reading)

    def advance_to(self, mono_ns: int) -> MeterReading | None:
        while len(self._readings) > 1 and self._readings[1].mono_ns <= mono_ns:
            self._readings.popleft()
        if self._readings and self._readings[0].mono_ns <= mono_ns:
            return self._readings[0]
        return None

    def __len__(self) -> int:
        return len(self._readings)
