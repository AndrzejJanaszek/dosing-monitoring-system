from uuid import UUID

from dms.domain.collisions import Overlap
from dms.domain.estimates import MissingReason
from dms.domain.estimation import MeanRateMethod
from dms.domain.events import EventKind
from dms.domain.finalizer import EventFinalizer
from dms.domain.rate_history import RateHistory, RateSampleRejected, rate_sample_of
from dms.domain.records import EventRecord
from dms.units import NS_PER_S
from tests.rate_history_cases import case_record


def overlap_with(kind: EventKind) -> Overlap:
    return Overlap(
        partner_id=UUID(int=99),
        partner_tank_id=1,
        partner_kind=kind,
        partner_start_known=True,
        partner_rule_violation=False,
        start_mono_ns=0,
        end_mono_ns=NS_PER_S,
        end_known=True,
    )


def test_finalizer_adds_a_clean_dispense_to_the_history_of_its_tank() -> None:
    histories = {1: RateHistory(3), 2: RateHistory(3)}
    finalizer = EventFinalizer(histories, [])
    record = case_record(1)

    outputs = finalizer.finalize(record.event, [])

    assert outputs == [record]
    assert histories[1].samples() == [rate_sample_of(record)]
    assert histories[2].samples() == []


def test_finalizer_keeps_a_collided_dispense_out_of_the_history() -> None:
    histories = {1: RateHistory(3)}
    finalizer = EventFinalizer(histories, [])

    (record,) = finalizer.finalize(case_record(1).event, [overlap_with(EventKind.REFILL)])

    assert record == case_record(1, collision=True)
    assert histories[1].samples() == []


def test_finalizer_reports_a_dispense_rejected_by_the_safety_check() -> None:
    histories = {1: RateHistory(3)}
    finalizer = EventFinalizer(histories, [])
    record = case_record(1, end_value_kg=1_000)

    outputs = finalizer.finalize(record.event, [])

    assert outputs == [
        record,
        RateSampleRejected(event_id=UUID(int=1), tank_id=1, mass_kg=0, duration_ns=12 * NS_PER_S),
    ]
    assert histories[1].samples() == []


def test_finalizer_estimates_a_collided_event_with_every_method() -> None:
    histories = {1: RateHistory(3)}
    finalizer = EventFinalizer(histories, [MeanRateMethod(2), MeanRateMethod(3)])

    (record,) = finalizer.finalize(case_record(1).event, [overlap_with(EventKind.REFILL)])

    assert isinstance(record, EventRecord)
    assert [(item.params, item.missing_reason) for item in record.estimates] == [
        ({"n": 2}, MissingReason.NO_RATE_HISTORY),
        ({"n": 3}, MissingReason.NO_RATE_HISTORY),
    ]


def test_finalizer_does_not_estimate_a_clean_event() -> None:
    finalizer = EventFinalizer({1: RateHistory(3)}, [MeanRateMethod(2)])

    record, *_ = finalizer.finalize(case_record(1).event, [])

    assert isinstance(record, EventRecord)
    assert record.estimates == ()
