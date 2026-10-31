from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from dms.domain.events import EventKind, EventStatus
from dms.domain.records import EventRecord

DEFAULT_RATE_HISTORY_CAPACITY = 10


@dataclass(frozen=True, slots=True, kw_only=True)
class RateSample:
    event_id: UUID
    mass_kg: int
    duration_ns: int


@dataclass(frozen=True, slots=True, kw_only=True)
class RateSampleRejected:
    event_id: UUID
    tank_id: int
    mass_kg: int
    duration_ns: int


def rate_sample_of(record: EventRecord) -> RateSample | RateSampleRejected | None:
    event = record.event
    if (
        event.kind is not EventKind.DISPENSE
        or event.status is not EventStatus.COMPLETED
        or record.collision
        or record.rule_violation
        or event.start_value_kg is None
        or event.end_value_kg is None
        or event.duration_ns is None
    ):
        return None

    mass_kg = event.start_value_kg - event.end_value_kg
    if mass_kg <= 0 or event.duration_ns <= 0:
        return RateSampleRejected(
            event_id=event.event_id,
            tank_id=event.tank_id,
            mass_kg=mass_kg,
            duration_ns=event.duration_ns,
        )
    return RateSample(event_id=event.event_id, mass_kg=mass_kg, duration_ns=event.duration_ns)


class RateHistory:
    def __init__(self, capacity: int, samples: Sequence[RateSample] = ()) -> None:
        self._samples: deque[RateSample] = deque(samples, maxlen=capacity)

    def add(self, sample: RateSample) -> None:
        self._samples.append(sample)

    def samples(self) -> list[RateSample]:
        return list(self._samples)
