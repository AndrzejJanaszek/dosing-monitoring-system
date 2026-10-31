from collections.abc import Mapping, Sequence
from statistics import fmean

from dms.domain.collisions import Overlap
from dms.domain.estimates import EstimationMethodId, EventEstimate, MissingReason
from dms.domain.events import ClosedEvent, EventKind
from dms.domain.rate_history import RateHistory


class MeanRateMethod:
    def __init__(self, n: int) -> None:
        self._n = n

    @property
    def params(self) -> dict[str, int]:
        return {"n": self._n}

    def estimate(
        self,
        event: ClosedEvent,
        overlaps: Sequence[Overlap],
        histories: Mapping[int, RateHistory],
    ) -> EventEstimate:
        reason = self._missing_reason(event, overlaps, histories)
        if reason is not None:
            return self._result(value_kg=None, missing_reason=reason)

        if event.kind is EventKind.DISPENSE:
            value_kg = self._dispensed_kg(event.tank_id, event.duration_ns, histories)
        else:
            value_kg = self._refilled_kg(event, overlaps, histories)
        return self._result(value_kg=round(value_kg), missing_reason=None)

    def _missing_reason(
        self,
        event: ClosedEvent,
        overlaps: Sequence[Overlap],
        histories: Mapping[int, RateHistory],
    ) -> MissingReason | None:
        if any(overlap.partner_kind is event.kind for overlap in overlaps):
            return MissingReason.RULE_VIOLATION
        if event.kind is EventKind.REFILL and any(
            overlap.partner_rule_violation for overlap in overlaps
        ):
            return MissingReason.OVERLAP_WITH_RULE_VIOLATION

        if event.kind is EventKind.DISPENSE:
            data_reason = _dispense_data_reason(event)
            needed_tanks = [event.tank_id]
        else:
            data_reason = _refill_data_reason(event)
            needed_tanks = [overlap.partner_tank_id for overlap in overlaps]
        if data_reason is not None:
            return data_reason

        if any(len(histories[tank_id].samples()) < self._n for tank_id in needed_tanks):
            return MissingReason.NO_RATE_HISTORY
        return None

    def _rate_kg_per_ns(self, tank_id: int, histories: Mapping[int, RateHistory]) -> float:
        samples = histories[tank_id].samples()[-self._n :]
        return fmean(sample.mass_kg / sample.duration_ns for sample in samples)

    def _dispensed_kg(
        self, tank_id: int, duration_ns: int | None, histories: Mapping[int, RateHistory]
    ) -> float:
        if duration_ns is None:
            raise ValueError(f"dispense of tank {tank_id} has no duration")
        return self._rate_kg_per_ns(tank_id, histories) * duration_ns

    def _refilled_kg(
        self,
        event: ClosedEvent,
        overlaps: Sequence[Overlap],
        histories: Mapping[int, RateHistory],
    ) -> float:
        if event.start_value_kg is None or event.end_value_kg is None:
            raise ValueError(f"refill {event.event_id} has no measured change")
        dispensed_kg = sum(
            self._dispensed_kg(overlap.partner_tank_id, overlap.duration_ns, histories)
            for overlap in overlaps
        )
        return event.end_value_kg - event.start_value_kg + dispensed_kg

    def _result(
        self, *, value_kg: int | None, missing_reason: MissingReason | None
    ) -> EventEstimate:
        return EventEstimate(
            method=EstimationMethodId.MEAN_RATE,
            params=self.params,
            value_kg=value_kg,
            missing_reason=missing_reason,
        )


def _dispense_data_reason(event: ClosedEvent) -> MissingReason | None:
    if not event.started_on_signal_edge or not event.ended_on_signal_edge:
        return MissingReason.UNKNOWN_DURATION
    return None


def _refill_data_reason(event: ClosedEvent) -> MissingReason | None:
    if event.start_value_kg is None or event.end_value_kg is None:
        return MissingReason.UNMEASURED_CHANGE
    return None
