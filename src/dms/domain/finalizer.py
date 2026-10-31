from collections.abc import Mapping, Sequence

from dms.domain.collisions import Overlap
from dms.domain.estimation import MeanRateMethod
from dms.domain.events import ClosedEvent
from dms.domain.rate_history import RateHistory, RateSample, RateSampleRejected, rate_sample_of
from dms.domain.records import EventRecord


class EventFinalizer:
    def __init__(
        self, histories: Mapping[int, RateHistory], methods: Sequence[MeanRateMethod]
    ) -> None:
        self._histories = histories
        self._methods = methods

    def finalize(
        self, event: ClosedEvent, overlaps: Sequence[Overlap]
    ) -> list[EventRecord | RateSampleRejected]:
        collision = bool(overlaps)
        estimates = (
            [method.estimate(event, overlaps, self._histories) for method in self._methods]
            if collision
            else []
        )
        record = EventRecord(
            event=event,
            collision=collision,
            rule_violation=any(overlap.partner_kind is event.kind for overlap in overlaps),
            estimates=tuple(estimates),
        )

        sample = rate_sample_of(record)
        if isinstance(sample, RateSample):
            self._histories[event.tank_id].add(sample)
            return [record]
        if isinstance(sample, RateSampleRejected):
            return [record, sample]
        return [record]
