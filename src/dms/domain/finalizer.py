from collections.abc import Mapping, Sequence

from dms.domain.collisions import Overlap
from dms.domain.events import ClosedEvent
from dms.domain.rate_history import RateHistory, RateSample, RateSampleRejected, rate_sample_of
from dms.domain.records import EventRecord


class EventFinalizer:
    def __init__(self, histories: Mapping[int, RateHistory]) -> None:
        self._histories = histories

    def finalize(
        self, event: ClosedEvent, overlaps: Sequence[Overlap]
    ) -> list[EventRecord | RateSampleRejected]:
        record = EventRecord(
            event=event,
            collision=bool(overlaps),
            rule_violation=any(overlap.partner_kind is event.kind for overlap in overlaps),
        )

        sample = rate_sample_of(record)
        if isinstance(sample, RateSample):
            self._histories[event.tank_id].add(sample)
            return [record]
        if isinstance(sample, RateSampleRejected):
            return [record, sample]
        return [record]
