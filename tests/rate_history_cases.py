from dataclasses import dataclass
from uuid import UUID

from dms.domain.events import ClosedEvent, EndQuality, EventKind, StartQuality
from dms.domain.rate_history import RateSample, RateSampleRejected
from dms.domain.records import EventRecord
from dms.units import NS_PER_MS, NS_PER_S

CASES_START_WALL_NS = 1_700_000_000 * NS_PER_S


@dataclass(frozen=True, slots=True, kw_only=True)
class RateCase:
    name: str
    record: EventRecord
    outcome: type[RateSample] | type[RateSampleRejected] | None


def case_record(
    number: int,
    *,
    tank_id: int = 1,
    kind: EventKind = EventKind.DISPENSE,
    start_value_kg: int = 1_000,
    end_value_kg: int | None = 400,
    duration_ms: int = 12_000,
    collision: bool = False,
    rule_violation: bool = False,
) -> EventRecord:
    start_wall_ns = CASES_START_WALL_NS + number * 100 * NS_PER_S
    return EventRecord(
        event=ClosedEvent(
            event_id=UUID(int=number),
            tank_id=tank_id,
            kind=kind,
            start_wall_ns=start_wall_ns,
            start_value_kg=start_value_kg,
            end_wall_ns=start_wall_ns + duration_ms * NS_PER_MS,
            end_value_kg=end_value_kg,
            duration_ns=duration_ms * NS_PER_MS,
            start_quality=StartQuality.FRESH,
            end_quality=EndQuality.FRESH if end_value_kg is not None else EndQuality.STALE_READING,
        ),
        collision=collision,
        rule_violation=rule_violation,
    )


RATE_CASES = [
    RateCase(name="clean-dispense", record=case_record(1), outcome=RateSample),
    RateCase(name="refill", record=case_record(2, kind=EventKind.REFILL), outcome=None),
    RateCase(name="incomplete", record=case_record(3, end_value_kg=None), outcome=None),
    RateCase(name="collision", record=case_record(4, collision=True), outcome=None),
    RateCase(
        name="rule-violation",
        record=case_record(5, collision=True, rule_violation=True),
        outcome=None,
    ),
    RateCase(
        name="zero-mass", record=case_record(6, end_value_kg=1_000), outcome=RateSampleRejected
    ),
    RateCase(
        name="negative-mass", record=case_record(7, end_value_kg=1_200), outcome=RateSampleRejected
    ),
    RateCase(
        name="zero-duration", record=case_record(8, duration_ms=0), outcome=RateSampleRejected
    ),
    RateCase(
        name="other-clean-dispense",
        record=case_record(9, start_value_kg=5_000, end_value_kg=3_980, duration_ms=20_250),
        outcome=RateSample,
    ),
]
