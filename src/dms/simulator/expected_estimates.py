from collections.abc import Sequence
from dataclasses import dataclass
from statistics import fmean

from dms.domain.estimates import MissingReason
from dms.domain.events import EndQuality, EventKind, StartQuality
from dms.simulator.expected_events import ExpectedEvent
from dms.simulator.scenario import Scenario
from dms.simulator.scenario_model import SimulatedTankEvent
from dms.units import NS_PER_S

EDGES_PER_INTERVAL = 2
ROUNDING_KG = 1.0


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpectedEstimate:
    missing_reason: MissingReason | None
    true_kg: int | None
    tolerance_kg: float


def expected_estimates(
    scenario: Scenario, events: Sequence[ExpectedEvent], *, n: int
) -> dict[ExpectedEvent, ExpectedEstimate]:
    estimator = _Estimator(scenario, events, n)
    return {event: estimator.estimate(event) for event in events if event.collision}


@dataclass(frozen=True, slots=True, kw_only=True)
class _Rate:
    kg_per_s: float
    sample_duration_s: float


class _Estimator:
    def __init__(self, scenario: Scenario, events: Sequence[ExpectedEvent], n: int) -> None:
        self._scenario = scenario
        self._events = events
        self._n = n
        self._pins_period_s = scenario.layout.board.pins_period_s

    def estimate(self, event: ExpectedEvent) -> ExpectedEstimate:
        overlapping = self._overlapping(event)
        reason = self._missing_reason(event, overlapping)
        if reason is not None:
            return ExpectedEstimate(missing_reason=reason, true_kg=None, tolerance_kg=0.0)

        truth = self._truth(event)
        division_kg = self._scenario.layout.silo_of(event.tank_id).meter.division_kg
        if event.kind is EventKind.DISPENSE:
            tolerance_kg = self._interval_tolerance_kg(
                self._rate(event.tank_id, event.end_ns), truth.end_s - truth.start_s, division_kg
            )
        else:
            tolerance_kg = division_kg + sum(
                self._interval_tolerance_kg(
                    self._rate(other.tank_id, event.end_ns),
                    _overlap_s(truth, self._truth(other)),
                    division_kg,
                )
                for other in overlapping
            )
        return ExpectedEstimate(
            missing_reason=None, true_kg=truth.mass_kg, tolerance_kg=tolerance_kg + ROUNDING_KG
        )

    def _missing_reason(
        self, event: ExpectedEvent, overlapping: list[ExpectedEvent]
    ) -> MissingReason | None:
        if any(other.kind is event.kind for other in overlapping):
            return MissingReason.RULE_VIOLATION
        if event.kind is EventKind.REFILL and any(
            self._violation_seen_before(other, event.end_ns) for other in overlapping
        ):
            return MissingReason.OVERLAP_WITH_RULE_VIOLATION

        data_reason = _data_reason(event, overlapping)
        if data_reason is not None:
            return data_reason

        needed_tanks = (
            [event.tank_id]
            if event.kind is EventKind.DISPENSE
            else [other.tank_id for other in overlapping]
        )
        if any(
            len(self._clean_dispenses(tank_id, event.end_ns)) < self._n for tank_id in needed_tanks
        ):
            return MissingReason.NO_RATE_HISTORY
        return None

    def _overlapping(self, event: ExpectedEvent) -> list[ExpectedEvent]:
        return [
            other
            for other in self._events
            if other is not event and self._same_silo(event, other) and _intersect(event, other)
        ]

    def _violation_seen_before(self, partner: ExpectedEvent, until_ns: int) -> bool:
        return any(
            other.kind is partner.kind
            and other.tank_id != partner.tank_id
            and self._same_silo(partner, other)
            and _intersect(partner, other)
            and max(partner.start_ns, other.start_ns) < until_ns
            for other in self._events
        )

    def _clean_dispenses(self, tank_id: int, until_ns: int) -> list[ExpectedEvent]:
        return [
            other
            for other in self._events
            if other.tank_id == tank_id
            and other.kind is EventKind.DISPENSE
            and other.start_quality is StartQuality.FRESH
            and other.end_quality is EndQuality.FRESH
            and not other.collision
            and other.end_ns <= until_ns
        ]

    def _rate(self, tank_id: int, until_ns: int) -> _Rate:
        samples = [self._truth(other) for other in self._clean_dispenses(tank_id, until_ns)]
        recent = samples[-self._n :]
        return _Rate(
            kg_per_s=fmean(sample.mass_kg / (sample.end_s - sample.start_s) for sample in recent),
            sample_duration_s=fmean(sample.end_s - sample.start_s for sample in recent),
        )

    def _interval_tolerance_kg(self, rate: _Rate, duration_s: float, division_kg: int) -> float:
        edge_error_s = EDGES_PER_INTERVAL * self._pins_period_s
        rate_error_kg_per_s = (
            division_kg + EDGES_PER_INTERVAL * self._pins_period_s * rate.kg_per_s
        ) / rate.sample_duration_s
        return (
            rate.kg_per_s * edge_error_s
            + duration_s * rate_error_kg_per_s
            + rate_error_kg_per_s * edge_error_s
        )

    def _truth(self, event: ExpectedEvent) -> SimulatedTankEvent:
        tolerance_ns = round(self._pins_period_s * NS_PER_S)
        return next(
            simulated
            for simulated in self._scenario.events
            if simulated.tank_id == event.tank_id
            and simulated.kind is event.kind
            and abs(simulated.end_ns - event.end_ns) <= tolerance_ns
        )

    def _same_silo(self, first: ExpectedEvent, second: ExpectedEvent) -> bool:
        layout = self._scenario.layout
        return layout.silo_of(first.tank_id).id == layout.silo_of(second.tank_id).id


def _data_reason(event: ExpectedEvent, overlapping: list[ExpectedEvent]) -> MissingReason | None:
    if event.kind is EventKind.DISPENSE:
        if event.start_quality is StartQuality.UNKNOWN or event.end_quality not in (
            EndQuality.FRESH,
            EndQuality.STALE_READING,
        ):
            return MissingReason.UNKNOWN_DURATION
        return None
    if event.start_value_kg is None or event.end_value_kg is None:
        return MissingReason.UNMEASURED_CHANGE
    if any(other.start_quality is StartQuality.UNKNOWN for other in overlapping):
        return MissingReason.UNKNOWN_OVERLAP
    return None


def _intersect(first: ExpectedEvent, second: ExpectedEvent) -> bool:
    return first.start_ns < second.end_ns and second.start_ns < first.end_ns


def _overlap_s(first: SimulatedTankEvent, second: SimulatedTankEvent) -> float:
    return max(0.0, min(first.end_s, second.end_s) - max(first.start_s, second.start_s))
