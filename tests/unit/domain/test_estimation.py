from collections.abc import Sequence
from uuid import UUID

import pytest

from dms.domain.collisions import Overlap
from dms.domain.estimates import EstimationMethodId, EventEstimate, MissingReason
from dms.domain.estimation import MeanRateMethod
from dms.domain.events import ClosedEvent, EndQuality, EventKind, StartQuality
from dms.domain.rate_history import RateHistory, RateSample
from dms.units import NS_PER_S

N = 2
REFILL_ID = UUID(int=100)
DISPENSE_ID = UUID(int=200)
OTHER_DISPENSE_ID = UUID(int=300)


def history(*rates_kg_per_s: float) -> RateHistory:
    return RateHistory(
        10,
        [
            RateSample(
                event_id=UUID(int=number),
                mass_kg=round(rate * 10),
                duration_ns=10 * NS_PER_S,
            )
            for number, rate in enumerate(rates_kg_per_s, start=1)
        ],
    )


HISTORIES = {1: history(40, 50, 60), 2: history(20, 20), 3: history(30)}


def event(
    kind: EventKind,
    *,
    tank_id: int = 1,
    start_s: float = 100,
    end_s: float = 130,
    start_value_kg: int | None = 10_000,
    end_value_kg: int | None = 9_000,
    start_quality: StartQuality = StartQuality.FRESH,
    end_quality: EndQuality = EndQuality.FRESH,
) -> ClosedEvent:
    known_start = start_quality is not StartQuality.UNKNOWN
    return ClosedEvent(
        event_id=REFILL_ID if kind is EventKind.REFILL else DISPENSE_ID,
        tank_id=tank_id,
        kind=kind,
        start_wall_ns=round(start_s * NS_PER_S),
        start_value_kg=start_value_kg if known_start else None,
        end_wall_ns=round(end_s * NS_PER_S),
        end_value_kg=end_value_kg,
        duration_ns=round((end_s - start_s) * NS_PER_S) if known_start else None,
        start_quality=start_quality,
        end_quality=end_quality,
    )


def overlap(
    *,
    partner_kind: EventKind = EventKind.DISPENSE,
    partner_tank_id: int = 1,
    partner_id: UUID = DISPENSE_ID,
    start_s: float = 110,
    end_s: float = 120,
    partner_start_known: bool = True,
    end_known: bool = True,
    partner_rule_violation: bool = False,
) -> Overlap:
    return Overlap(
        partner_id=partner_id,
        partner_tank_id=partner_tank_id,
        partner_kind=partner_kind,
        partner_start_known=partner_start_known,
        partner_rule_violation=partner_rule_violation,
        start_mono_ns=round(start_s * NS_PER_S),
        end_mono_ns=round(end_s * NS_PER_S),
        end_known=end_known,
    )


def estimate(closed: ClosedEvent, overlaps: Sequence[Overlap]) -> EventEstimate:
    return MeanRateMethod(N).estimate(closed, overlaps, HISTORIES)


def test_dispense_is_the_mean_rate_of_the_last_n_samples_times_its_duration() -> None:
    result = estimate(event(EventKind.DISPENSE), [overlap(partner_kind=EventKind.REFILL)])

    assert result == EventEstimate(
        method=EstimationMethodId.MEAN_RATE,
        params={"n": N},
        value_kg=55 * 30,
        missing_reason=None,
    )


def test_dispense_with_stale_readings_at_its_edges_is_estimated() -> None:
    closed = event(
        EventKind.DISPENSE,
        start_quality=StartQuality.STALE_READING,
        end_quality=EndQuality.STALE_READING,
        end_value_kg=None,
    )

    assert estimate(closed, [overlap(partner_kind=EventKind.REFILL)]).value_kg == 1_650


def test_refill_adds_what_overlapping_dispenses_took_meanwhile() -> None:
    closed = event(EventKind.REFILL, tank_id=2, start_value_kg=5_000, end_value_kg=9_000)

    result = estimate(closed, [overlap(start_s=110, end_s=120)])

    assert result.value_kg == 4_000 + 55 * 10


def test_refill_uses_the_rate_of_the_tank_of_each_overlapping_dispense() -> None:
    closed = event(EventKind.REFILL, start_value_kg=5_000, end_value_kg=9_000)
    overlaps = [
        overlap(start_s=100, end_s=110),
        overlap(partner_id=OTHER_DISPENSE_ID, partner_tank_id=2, start_s=115, end_s=125),
        overlap(start_s=126, end_s=130),
    ]

    assert estimate(closed, overlaps).value_kg == 4_000 + 55 * 10 + 20 * 10 + 55 * 4


def test_refill_ending_while_the_dispense_goes_on_is_estimated_up_to_its_end() -> None:
    closed = event(EventKind.REFILL, start_value_kg=5_000, end_value_kg=9_000)

    assert estimate(closed, [overlap(start_s=125, end_s=130)]).value_kg == 4_000 + 55 * 5


def test_value_is_rounded_to_whole_kilograms() -> None:
    closed = event(EventKind.DISPENSE, start_s=100, end_s=100.01)

    assert estimate(closed, [overlap(partner_kind=EventKind.REFILL)]).value_kg == 1


@pytest.mark.parametrize(
    ("closed", "overlaps", "reason"),
    [
        (
            event(EventKind.DISPENSE),
            [overlap(partner_tank_id=2, partner_id=OTHER_DISPENSE_ID)],
            MissingReason.RULE_VIOLATION,
        ),
        (
            event(EventKind.REFILL),
            [overlap(partner_rule_violation=True)],
            MissingReason.OVERLAP_WITH_RULE_VIOLATION,
        ),
        (
            event(EventKind.DISPENSE, start_quality=StartQuality.UNKNOWN),
            [overlap(partner_kind=EventKind.REFILL)],
            MissingReason.UNKNOWN_DURATION,
        ),
        (
            event(EventKind.DISPENSE, end_quality=EndQuality.SIGNAL_LOST, end_value_kg=None),
            [overlap(partner_kind=EventKind.REFILL)],
            MissingReason.UNKNOWN_DURATION,
        ),
        (
            event(EventKind.DISPENSE, end_quality=EndQuality.SERVICE_STOPPED, end_value_kg=None),
            [overlap(partner_kind=EventKind.REFILL)],
            MissingReason.UNKNOWN_DURATION,
        ),
        (
            event(EventKind.REFILL, start_quality=StartQuality.STALE_READING, start_value_kg=None),
            [overlap()],
            MissingReason.UNMEASURED_CHANGE,
        ),
        (
            event(EventKind.REFILL, end_quality=EndQuality.SIGNAL_LOST, end_value_kg=None),
            [overlap()],
            MissingReason.UNMEASURED_CHANGE,
        ),
        (
            event(EventKind.REFILL),
            [overlap(partner_start_known=False)],
            MissingReason.UNKNOWN_OVERLAP,
        ),
        (
            event(EventKind.REFILL),
            [overlap(end_known=False)],
            MissingReason.UNKNOWN_OVERLAP,
        ),
        (
            event(EventKind.DISPENSE, tank_id=3),
            [overlap(partner_kind=EventKind.REFILL)],
            MissingReason.NO_RATE_HISTORY,
        ),
        (
            event(EventKind.REFILL),
            [overlap(), overlap(partner_tank_id=3, partner_id=OTHER_DISPENSE_ID)],
            MissingReason.NO_RATE_HISTORY,
        ),
    ],
    ids=[
        "rule-violation",
        "refill-over-a-rule-violation",
        "dispense-with-unknown-start",
        "dispense-ended-by-lost-signals",
        "dispense-ended-by-stop",
        "refill-without-start-value",
        "refill-ended-by-lost-signals",
        "dispense-with-unknown-start-under-refill",
        "overlap-ended-by-lost-signals",
        "dispense-tank-without-history",
        "refill-over-a-tank-without-history",
    ],
)
def test_estimate_is_missing_with_its_reason(
    closed: ClosedEvent, overlaps: list[Overlap], reason: MissingReason
) -> None:
    result = estimate(closed, overlaps)

    assert (result.value_kg, result.missing_reason) == (None, reason)


def test_dispense_over_a_refill_that_overlaps_a_rule_violation_is_still_estimated() -> None:
    result = estimate(
        event(EventKind.DISPENSE),
        [overlap(partner_kind=EventKind.REFILL, partner_rule_violation=True)],
    )

    assert result.value_kg == 1_650


@pytest.mark.parametrize(
    ("closed", "overlaps", "reason"),
    [
        (
            event(EventKind.DISPENSE, tank_id=3, start_quality=StartQuality.UNKNOWN),
            [overlap(partner_tank_id=2, partner_id=OTHER_DISPENSE_ID)],
            MissingReason.RULE_VIOLATION,
        ),
        (
            event(EventKind.REFILL, start_value_kg=None, start_quality=StartQuality.UNKNOWN),
            [overlap(partner_tank_id=3, partner_rule_violation=True)],
            MissingReason.OVERLAP_WITH_RULE_VIOLATION,
        ),
        (
            event(EventKind.DISPENSE, tank_id=3, start_quality=StartQuality.UNKNOWN),
            [overlap(partner_kind=EventKind.REFILL)],
            MissingReason.UNKNOWN_DURATION,
        ),
        (
            event(EventKind.REFILL, start_value_kg=None, start_quality=StartQuality.STALE_READING),
            [overlap(partner_tank_id=3, partner_start_known=False)],
            MissingReason.UNMEASURED_CHANGE,
        ),
        (
            event(EventKind.REFILL),
            [overlap(partner_tank_id=3, partner_start_known=False)],
            MissingReason.UNKNOWN_OVERLAP,
        ),
    ],
    ids=[
        "violation-before-missing-data",
        "violation-of-a-partner-before-missing-data",
        "missing-duration-before-missing-history",
        "unmeasured-change-before-unknown-overlap",
        "unknown-overlap-before-missing-history",
    ],
)
def test_first_reason_in_order_is_reported(
    closed: ClosedEvent, overlaps: list[Overlap], reason: MissingReason
) -> None:
    assert estimate(closed, overlaps).missing_reason is reason
