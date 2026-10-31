from uuid import UUID

from dms.domain.collisions import CollisionTracker, Overlap, RuleViolation
from dms.domain.events import EventKind, StartedEvent, StartQuality


def started(event_number: int, tank_id: int, kind: EventKind) -> StartedEvent:
    return StartedEvent(
        event_id=UUID(int=event_number),
        tank_id=tank_id,
        kind=kind,
        start_wall_ns=0,
        start_value_kg=None,
        start_quality=StartQuality.STALE_READING,
    )


REFILL = started(1, 1, EventKind.REFILL)
DISPENSE = started(2, 1, EventKind.DISPENSE)
OTHER_DISPENSE = started(3, 2, EventKind.DISPENSE)


def test_single_event_has_no_overlaps() -> None:
    tracker = CollisionTracker(1)
    tracker.on_started(DISPENSE, 10)

    assert tracker.on_closed(DISPENSE.event_id, 20, edge_known=True) == []


def test_partner_closed_first_gives_both_events_the_same_interval() -> None:
    tracker = CollisionTracker(1)
    tracker.on_started(REFILL, 10)
    tracker.on_started(DISPENSE, 30)

    dispense_overlaps = tracker.on_closed(DISPENSE.event_id, 50, edge_known=True)
    refill_overlaps = tracker.on_closed(REFILL.event_id, 90, edge_known=True)

    assert dispense_overlaps == [
        Overlap(
            partner_id=REFILL.event_id,
            partner_tank_id=1,
            partner_kind=EventKind.REFILL,
            partner_start_known=True,
            partner_rule_violation=False,
            start_mono_ns=30,
            end_mono_ns=50,
            end_known=True,
        )
    ]
    assert refill_overlaps == [
        Overlap(
            partner_id=DISPENSE.event_id,
            partner_tank_id=1,
            partner_kind=EventKind.DISPENSE,
            partner_start_known=True,
            partner_rule_violation=False,
            start_mono_ns=30,
            end_mono_ns=50,
            end_known=True,
        )
    ]


def test_partner_still_in_progress_ends_the_overlap_at_the_close() -> None:
    tracker = CollisionTracker(1)
    tracker.on_started(DISPENSE, 10)
    tracker.on_started(REFILL, 30)

    (refill_overlap,) = tracker.on_closed(REFILL.event_id, 50, edge_known=True)
    (dispense_overlap,) = tracker.on_closed(DISPENSE.event_id, 70, edge_known=True)

    assert (refill_overlap.start_mono_ns, refill_overlap.end_mono_ns) == (30, 50)
    assert refill_overlap.end_known
    assert (dispense_overlap.start_mono_ns, dispense_overlap.end_mono_ns) == (30, 50)
    assert refill_overlap.duration_ns == 20


def test_overlap_closed_without_a_signal_edge_has_an_unknown_end_for_both_events() -> None:
    tracker = CollisionTracker(1)
    tracker.on_started(REFILL, 10)
    tracker.on_started(DISPENSE, 30)

    (refill_overlap,) = tracker.on_closed(REFILL.event_id, 40, edge_known=False)
    (dispense_overlap,) = tracker.on_closed(DISPENSE.event_id, 40, edge_known=False)

    assert not refill_overlap.end_known
    assert not dispense_overlap.end_known


def test_event_closed_before_the_other_started_does_not_overlap_it() -> None:
    tracker = CollisionTracker(1)
    tracker.on_started(DISPENSE, 10)
    tracker.on_closed(DISPENSE.event_id, 30, edge_known=True)
    tracker.on_started(REFILL, 30)

    assert tracker.on_closed(REFILL.event_id, 90, edge_known=True) == []


def test_unknown_start_of_the_partner_takes_the_start_of_the_known_event() -> None:
    tracker = CollisionTracker(1)
    tracker.on_started(DISPENSE, None)
    tracker.on_started(REFILL, 30)

    (overlap,) = tracker.on_closed(REFILL.event_id, 50, edge_known=True)

    assert (overlap.start_mono_ns, overlap.partner_start_known) == (30, False)


def test_unknown_starts_of_both_events_leave_the_overlap_start_unknown() -> None:
    tracker = CollisionTracker(1)
    tracker.on_started(DISPENSE, None)
    tracker.on_started(REFILL, None)

    (overlap,) = tracker.on_closed(REFILL.event_id, 50, edge_known=True)

    assert overlap.start_mono_ns is None
    assert overlap.duration_ns is None


def test_same_type_on_the_other_tank_is_a_rule_violation_reported_once() -> None:
    tracker = CollisionTracker(7)
    tracker.on_started(DISPENSE, 10)

    violations = tracker.on_started(OTHER_DISPENSE, 20)

    assert violations == [
        RuleViolation(
            silo_id=7,
            kind=EventKind.DISPENSE,
            event_id=OTHER_DISPENSE.event_id,
            tank_id=2,
            other_event_id=DISPENSE.event_id,
            other_tank_id=1,
        )
    ]


def test_dispense_with_refill_is_not_a_rule_violation() -> None:
    tracker = CollisionTracker(1)
    tracker.on_started(REFILL, 10)

    assert tracker.on_started(OTHER_DISPENSE, 20) == []


def test_three_events_overlap_pairwise_and_the_refill_sees_the_violation() -> None:
    tracker = CollisionTracker(1)
    tracker.on_started(REFILL, 10)
    tracker.on_started(DISPENSE, 20)
    tracker.on_started(OTHER_DISPENSE, 30)

    first_dispense = tracker.on_closed(DISPENSE.event_id, 40, edge_known=True)
    second_dispense = tracker.on_closed(OTHER_DISPENSE.event_id, 50, edge_known=True)
    refill = tracker.on_closed(REFILL.event_id, 60, edge_known=True)

    assert {overlap.partner_id for overlap in first_dispense} == {
        REFILL.event_id,
        OTHER_DISPENSE.event_id,
    }
    assert {overlap.partner_id for overlap in second_dispense} == {
        REFILL.event_id,
        DISPENSE.event_id,
    }
    assert [(overlap.partner_id, overlap.partner_rule_violation) for overlap in refill] == [
        (DISPENSE.event_id, True),
        (OTHER_DISPENSE.event_id, True),
    ]


def test_violation_after_the_refill_ended_is_not_seen_by_the_refill() -> None:
    tracker = CollisionTracker(1)
    tracker.on_started(REFILL, 10)
    tracker.on_started(DISPENSE, 20)
    (refill_overlap,) = tracker.on_closed(REFILL.event_id, 30, edge_known=True)

    tracker.on_started(OTHER_DISPENSE, 40)

    assert not refill_overlap.partner_rule_violation


def test_closed_partner_keeps_its_violation_for_the_refill_that_ends_later() -> None:
    tracker = CollisionTracker(1)
    tracker.on_started(REFILL, 10)
    tracker.on_started(DISPENSE, 20)
    tracker.on_started(OTHER_DISPENSE, 30)
    tracker.on_closed(DISPENSE.event_id, 40, edge_known=True)
    tracker.on_closed(OTHER_DISPENSE.event_id, 50, edge_known=True)

    refill = tracker.on_closed(REFILL.event_id, 60, edge_known=True)

    assert all(overlap.partner_rule_violation for overlap in refill)


def test_finished_pairs_are_forgotten() -> None:
    tracker = CollisionTracker(1)
    tracker.on_started(REFILL, 10)
    tracker.on_started(DISPENSE, 20)
    tracker.on_closed(DISPENSE.event_id, 30, edge_known=True)
    tracker.on_closed(REFILL.event_id, 40, edge_known=True)
    tracker.on_started(OTHER_DISPENSE, 50)

    assert tracker.on_closed(OTHER_DISPENSE.event_id, 60, edge_known=True) == []
