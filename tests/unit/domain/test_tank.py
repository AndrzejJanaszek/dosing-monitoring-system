from uuid import UUID

from dms.domain.events import ClosedEvent, StartedEvent
from dms.domain.tank import SignalChange, Tank, TankOutput
from dms.messages import TankSignals
from tests.unit.domain.builders import sequential_ids

SECOND_NS = 1_000_000_000
SERVICE_START_WALL_NS = 1_000 * SECOND_NS


def signals(dispense: bool, refill: bool) -> TankSignals:
    return TankSignals(3, dispense=dispense, refill=refill)


def build_tank() -> Tank:
    return Tank(3, sequential_ids(), SERVICE_START_WALL_NS)


def feed(
    tank: Tank, dispense: bool, refill: bool, second: int, value_kg: int | None = 100
) -> list[TankOutput]:
    wall_ns = (2_000 + second) * SECOND_NS
    return tank.on_signals(signals(dispense, refill), wall_ns, second * SECOND_NS, value_kg)


def events_only(outputs: list[TankOutput]) -> list[StartedEvent | ClosedEvent]:
    return [item for item in outputs if isinstance(item, StartedEvent | ClosedEvent)]


def closed_events(outputs: list[TankOutput]) -> list[ClosedEvent]:
    return [item for item in outputs if isinstance(item, ClosedEvent)]


def event_id(number: int) -> UUID:
    return UUID(int=number)


def test_first_snapshot_reports_both_signals_with_unknown_previous_state() -> None:
    changes = build_tank().on_signals(signals(False, True), 0, 0, None)

    assert [item for item in changes if isinstance(item, SignalChange)] == [
        SignalChange(3, "dispense", False, None),
        SignalChange(3, "refill", True, None),
    ]


def test_only_the_changed_signal_is_reported() -> None:
    tank = build_tank()
    feed(tank, False, False, 1)

    outputs = feed(tank, True, False, 2)

    assert outputs[0] == SignalChange(3, "dispense", True, False)
    assert [item for item in outputs if isinstance(item, SignalChange)] == [outputs[0]]


def test_unchanged_snapshot_reports_nothing() -> None:
    tank = build_tank()
    feed(tank, True, False, 1)

    assert feed(tank, True, False, 2) == []


def test_both_signals_changing_are_reported_dispense_first() -> None:
    tank = build_tank()
    feed(tank, False, False, 1)

    outputs = feed(tank, True, True, 2)

    assert [item.signal for item in outputs if isinstance(item, SignalChange)] == [
        "dispense",
        "refill",
    ]


def test_signal_changes_come_before_events() -> None:
    tank = build_tank()
    feed(tank, False, False, 1)

    outputs = feed(tank, True, True, 2)

    assert [type(item) for item in outputs] == [
        SignalChange,
        SignalChange,
        StartedEvent,
        StartedEvent,
    ]
    assert [item.kind for item in events_only(outputs)] == ["dispense", "refill"]


def test_first_inactive_snapshot_starts_no_event() -> None:
    assert events_only(feed(build_tank(), False, False, 1)) == []


def test_active_signal_starts_an_event_with_the_value_at_the_edge() -> None:
    tank = build_tank()
    feed(tank, False, False, 1)

    started = events_only(feed(tank, True, False, 2, value_kg=500))

    assert started == [StartedEvent(event_id(1), 3, "dispense", 2_002 * SECOND_NS, 500, "fresh")]


def test_event_completes_with_values_and_monotonic_duration() -> None:
    tank = build_tank()
    feed(tank, False, False, 1)
    feed(tank, True, False, 2, value_kg=500)

    closed = closed_events(feed(tank, False, False, 12, value_kg=380))

    assert closed == [
        ClosedEvent(
            event_id(1),
            3,
            "dispense",
            2_002 * SECOND_NS,
            500,
            2_012 * SECOND_NS,
            380,
            10 * SECOND_NS,
            "fresh",
            "fresh",
        )
    ]
    assert closed[0].status == "completed"


def test_active_snapshots_during_an_event_change_nothing() -> None:
    tank = build_tank()
    feed(tank, False, False, 1)
    feed(tank, True, False, 2)

    assert feed(tank, True, False, 3) == []


def test_next_event_gets_a_new_id() -> None:
    tank = build_tank()
    feed(tank, False, False, 1)
    first = events_only(feed(tank, True, False, 2))
    feed(tank, False, False, 3)

    second = events_only(feed(tank, True, False, 4))

    assert [item.event_id for item in first + second] == [event_id(1), event_id(2)]


def test_stale_start_reading_keeps_the_event_and_completes_it_as_incomplete() -> None:
    tank = build_tank()
    feed(tank, False, False, 1)
    started = events_only(feed(tank, True, False, 2, value_kg=None))

    closed = closed_events(feed(tank, False, False, 5, value_kg=300))

    assert started[0].start_value_kg is None
    assert closed == [
        ClosedEvent(
            event_id(1),
            3,
            "dispense",
            2_002 * SECOND_NS,
            None,
            2_005 * SECOND_NS,
            300,
            3 * SECOND_NS,
            "stale_reading",
            "fresh",
        )
    ]
    assert closed[0].status == "incomplete"


def test_stale_end_reading_leaves_the_end_value_empty() -> None:
    tank = build_tank()
    feed(tank, False, False, 1)
    feed(tank, True, False, 2, value_kg=500)

    closed = events_only(feed(tank, False, False, 5, value_kg=None))

    assert closed == [
        ClosedEvent(
            event_id(1),
            3,
            "dispense",
            2_002 * SECOND_NS,
            500,
            2_005 * SECOND_NS,
            None,
            3 * SECOND_NS,
            "fresh",
            "stale_reading",
        )
    ]


def test_stale_start_and_stale_end_are_both_recorded() -> None:
    tank = build_tank()
    feed(tank, False, False, 1)
    feed(tank, True, False, 2, value_kg=None)

    closed = events_only(feed(tank, False, False, 5, value_kg=None))

    assert isinstance(closed[0], ClosedEvent)
    assert (closed[0].start_quality, closed[0].end_quality) == ("stale_reading", "stale_reading")
    assert closed[0].end_value_kg is None


def test_active_signal_in_the_first_snapshot_starts_an_orphaned_event_at_service_start() -> None:
    started = events_only(feed(build_tank(), True, False, 1, value_kg=500))

    assert started == [
        StartedEvent(event_id(1), 3, "dispense", SERVICE_START_WALL_NS, None, "unknown")
    ]


def test_orphaned_event_closes_with_unknown_start_the_end_value_and_no_duration() -> None:
    tank = build_tank()
    feed(tank, True, False, 1)

    closed = events_only(feed(tank, False, False, 8, value_kg=250))

    assert closed == [
        ClosedEvent(
            event_id(1),
            3,
            "dispense",
            SERVICE_START_WALL_NS,
            None,
            2_008 * SECOND_NS,
            250,
            None,
            "unknown",
            "fresh",
        )
    ]


def test_orphaned_event_with_stale_end_records_both_qualities() -> None:
    tank = build_tank()
    feed(tank, True, False, 1)

    closed = events_only(feed(tank, False, False, 8, value_kg=None))

    assert isinstance(closed[0], ClosedEvent)
    assert (closed[0].start_quality, closed[0].end_quality) == ("unknown", "stale_reading")
    assert closed[0].end_value_kg is None


def test_orphaned_event_continues_while_the_signal_stays_active() -> None:
    tank = build_tank()
    feed(tank, True, False, 1)

    assert feed(tank, True, False, 2) == []


def test_loss_closes_an_event_in_progress_as_signal_lost_at_the_last_fresh_snapshot() -> None:
    tank = build_tank()
    feed(tank, False, False, 1)
    feed(tank, True, False, 2, value_kg=500)

    closed = tank.on_signals_lost(2_004 * SECOND_NS, 4 * SECOND_NS)

    assert closed == [
        ClosedEvent(
            event_id(1),
            3,
            "dispense",
            2_002 * SECOND_NS,
            500,
            2_004 * SECOND_NS,
            None,
            2 * SECOND_NS,
            "fresh",
            "signal_lost",
        )
    ]


def test_loss_in_progress_with_stale_start_records_both_qualities() -> None:
    tank = build_tank()
    feed(tank, False, False, 1)
    feed(tank, True, False, 2, value_kg=None)

    closed = tank.on_signals_lost(2_004 * SECOND_NS, 4 * SECOND_NS)

    assert (closed[0].start_quality, closed[0].end_quality) == ("stale_reading", "signal_lost")


def test_loss_closes_an_orphaned_event_as_signal_lost_with_unknown_start() -> None:
    tank = build_tank()
    feed(tank, True, False, 1)

    closed = tank.on_signals_lost(2_004 * SECOND_NS, 4 * SECOND_NS)

    assert closed == [
        ClosedEvent(
            event_id(1),
            3,
            "dispense",
            SERVICE_START_WALL_NS,
            None,
            2_004 * SECOND_NS,
            None,
            None,
            "unknown",
            "signal_lost",
        )
    ]


def test_loss_with_an_event_of_zero_duration_gives_zero_duration() -> None:
    tank = build_tank()
    feed(tank, False, False, 1)
    feed(tank, True, False, 2)

    closed = tank.on_signals_lost(2_002 * SECOND_NS, 2 * SECOND_NS)

    assert closed[0].duration_ns == 0


def test_loss_closes_both_signals_dispense_first() -> None:
    tank = build_tank()
    feed(tank, False, False, 1)
    feed(tank, True, True, 2)

    closed = tank.on_signals_lost(2_004 * SECOND_NS, 4 * SECOND_NS)

    assert [item.kind for item in closed] == ["dispense", "refill"]


def test_loss_without_open_events_closes_nothing() -> None:
    tank = build_tank()
    feed(tank, False, False, 1)

    assert tank.on_signals_lost(2_004 * SECOND_NS, 4 * SECOND_NS) == []


def test_after_loss_the_next_snapshot_reports_unknown_previous_states() -> None:
    tank = build_tank()
    feed(tank, True, False, 1)
    tank.on_signals_lost(2_004 * SECOND_NS, 4 * SECOND_NS)

    outputs = feed(tank, True, False, 9)

    assert [item for item in outputs if isinstance(item, SignalChange)] == [
        SignalChange(3, "dispense", True, None),
        SignalChange(3, "refill", False, None),
    ]


def test_active_signal_after_loss_starts_an_orphaned_event_at_the_last_fresh_snapshot() -> None:
    tank = build_tank()
    feed(tank, False, False, 1)
    feed(tank, True, False, 2)
    tank.on_signals_lost(2_004 * SECOND_NS, 4 * SECOND_NS)

    started = events_only(feed(tank, True, False, 9, value_kg=400))

    assert started == [StartedEvent(event_id(2), 3, "dispense", 2_004 * SECOND_NS, None, "unknown")]


def test_inactive_signal_after_loss_starts_no_event() -> None:
    tank = build_tank()
    feed(tank, True, False, 1)
    tank.on_signals_lost(2_004 * SECOND_NS, 4 * SECOND_NS)

    assert events_only(feed(tank, False, False, 9)) == []


def test_after_loss_without_signals_the_orphaned_start_is_the_service_start() -> None:
    tank = build_tank()
    tank.on_signals_lost(SERVICE_START_WALL_NS, 0)

    started = events_only(feed(tank, True, False, 9))

    assert started[0].start_wall_ns == SERVICE_START_WALL_NS


def test_skipped_snapshot_puts_the_change_at_the_next_snapshot() -> None:
    tank = build_tank()
    feed(tank, False, False, 1)

    started = events_only(feed(tank, True, False, 4, value_kg=450))

    assert started[0].start_wall_ns == 2_004 * SECOND_NS
    assert started[0].start_value_kg == 450


def test_dispense_and_refill_overlap_on_one_tank_independently() -> None:
    tank = build_tank()
    feed(tank, False, False, 1)
    feed(tank, True, False, 2, value_kg=500)
    feed(tank, True, True, 3, value_kg=480)

    closed_dispense = events_only(feed(tank, False, True, 4, value_kg=470))
    closed_refill = events_only(feed(tank, False, False, 5, value_kg=600))

    assert [(item.kind, item.event_id) for item in closed_dispense] == [("dispense", event_id(1))]
    assert [(item.kind, item.event_id) for item in closed_refill] == [("refill", event_id(2))]
