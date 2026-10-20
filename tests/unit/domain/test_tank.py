from uuid import UUID

from dms.domain.events import ClosedEvent, EndQuality, EventKind, StartedEvent, StartQuality
from dms.domain.tank import SignalChange, Tank, TankOutput
from dms.messages import TankSignals
from dms.units import NS_PER_S
from tests.unit.domain.builders import sequential_ids

SERVICE_START_WALL_NS = 1_000 * NS_PER_S


def signals(*, dispense: bool, refill: bool) -> TankSignals:
    return TankSignals(3, dispense=dispense, refill=refill)


def build_tank() -> Tank:
    return Tank(3, sequential_ids(), SERVICE_START_WALL_NS)


def feed(
    tank: Tank,
    second: int,
    *,
    dispense: bool = False,
    refill: bool = False,
    value_kg: int | None = 100,
) -> list[TankOutput]:
    wall_ns = (2_000 + second) * NS_PER_S
    return tank.on_signals(
        signals(dispense=dispense, refill=refill), wall_ns, second * NS_PER_S, value_kg
    )


def events_only(outputs: list[TankOutput]) -> list[StartedEvent | ClosedEvent]:
    return [item for item in outputs if isinstance(item, StartedEvent | ClosedEvent)]


def closed_events(outputs: list[TankOutput]) -> list[ClosedEvent]:
    return [item for item in outputs if isinstance(item, ClosedEvent)]


def event_id(number: int) -> UUID:
    return UUID(int=number)


def test_first_snapshot_reports_both_signals_with_unknown_previous_state() -> None:
    changes = build_tank().on_signals(signals(dispense=False, refill=True), 0, 0, None)

    assert [item for item in changes if isinstance(item, SignalChange)] == [
        SignalChange(tank_id=3, signal=EventKind.DISPENSE, active=False, previous=None),
        SignalChange(tank_id=3, signal=EventKind.REFILL, active=True, previous=None),
    ]


def test_only_the_changed_signal_is_reported() -> None:
    tank = build_tank()
    feed(tank, 1)

    outputs = feed(tank, 2, dispense=True)

    assert outputs[0] == SignalChange(
        tank_id=3, signal=EventKind.DISPENSE, active=True, previous=False
    )
    assert [item for item in outputs if isinstance(item, SignalChange)] == [outputs[0]]


def test_unchanged_snapshot_reports_nothing() -> None:
    tank = build_tank()
    feed(tank, 1, dispense=True)

    assert feed(tank, 2, dispense=True) == []


def test_both_signals_changing_are_reported_dispense_first() -> None:
    tank = build_tank()
    feed(tank, 1)

    outputs = feed(tank, 2, dispense=True, refill=True)

    assert [item.signal for item in outputs if isinstance(item, SignalChange)] == [
        "dispense",
        "refill",
    ]


def test_signal_changes_come_before_events() -> None:
    tank = build_tank()
    feed(tank, 1)

    outputs = feed(tank, 2, dispense=True, refill=True)

    assert [type(item) for item in outputs] == [
        SignalChange,
        SignalChange,
        StartedEvent,
        StartedEvent,
    ]
    assert [item.kind for item in events_only(outputs)] == ["dispense", "refill"]


def test_first_inactive_snapshot_starts_no_event() -> None:
    assert events_only(feed(build_tank(), 1)) == []


def test_active_signal_starts_an_event_with_the_value_at_the_edge() -> None:
    tank = build_tank()
    feed(tank, 1)

    started = events_only(feed(tank, 2, dispense=True, value_kg=500))

    assert started == [
        StartedEvent(
            event_id=event_id(1),
            tank_id=3,
            kind=EventKind.DISPENSE,
            start_wall_ns=2_002 * NS_PER_S,
            start_value_kg=500,
            start_quality=StartQuality.FRESH,
        )
    ]


def test_event_completes_with_values_and_monotonic_duration() -> None:
    tank = build_tank()
    feed(tank, 1)
    feed(tank, 2, dispense=True, value_kg=500)

    closed = closed_events(feed(tank, 12, value_kg=380))

    assert closed == [
        ClosedEvent(
            event_id=event_id(1),
            tank_id=3,
            kind=EventKind.DISPENSE,
            start_wall_ns=2_002 * NS_PER_S,
            start_value_kg=500,
            end_wall_ns=2_012 * NS_PER_S,
            end_value_kg=380,
            duration_ns=10 * NS_PER_S,
            start_quality=StartQuality.FRESH,
            end_quality=EndQuality.FRESH,
        )
    ]
    assert closed[0].status == "completed"


def test_active_snapshots_during_an_event_change_nothing() -> None:
    tank = build_tank()
    feed(tank, 1)
    feed(tank, 2, dispense=True)

    assert feed(tank, 3, dispense=True) == []


def test_next_event_gets_a_new_id() -> None:
    tank = build_tank()
    feed(tank, 1)
    first = events_only(feed(tank, 2, dispense=True))
    feed(tank, 3)

    second = events_only(feed(tank, 4, dispense=True))

    assert [item.event_id for item in first + second] == [event_id(1), event_id(2)]


def test_stale_start_reading_keeps_the_event_and_completes_it_as_incomplete() -> None:
    tank = build_tank()
    feed(tank, 1)
    started = events_only(feed(tank, 2, dispense=True, value_kg=None))

    closed = closed_events(feed(tank, 5, value_kg=300))

    assert started[0].start_value_kg is None
    assert closed == [
        ClosedEvent(
            event_id=event_id(1),
            tank_id=3,
            kind=EventKind.DISPENSE,
            start_wall_ns=2_002 * NS_PER_S,
            start_value_kg=None,
            end_wall_ns=2_005 * NS_PER_S,
            end_value_kg=300,
            duration_ns=3 * NS_PER_S,
            start_quality=StartQuality.STALE_READING,
            end_quality=EndQuality.FRESH,
        )
    ]
    assert closed[0].status == "incomplete"


def test_stale_end_reading_leaves_the_end_value_empty() -> None:
    tank = build_tank()
    feed(tank, 1)
    feed(tank, 2, dispense=True, value_kg=500)

    closed = events_only(feed(tank, 5, value_kg=None))

    assert closed == [
        ClosedEvent(
            event_id=event_id(1),
            tank_id=3,
            kind=EventKind.DISPENSE,
            start_wall_ns=2_002 * NS_PER_S,
            start_value_kg=500,
            end_wall_ns=2_005 * NS_PER_S,
            end_value_kg=None,
            duration_ns=3 * NS_PER_S,
            start_quality=StartQuality.FRESH,
            end_quality=EndQuality.STALE_READING,
        )
    ]


def test_stale_start_and_stale_end_are_both_recorded() -> None:
    tank = build_tank()
    feed(tank, 1)
    feed(tank, 2, dispense=True, value_kg=None)

    closed = events_only(feed(tank, 5, value_kg=None))

    assert isinstance(closed[0], ClosedEvent)
    assert (closed[0].start_quality, closed[0].end_quality) == ("stale_reading", "stale_reading")
    assert closed[0].end_value_kg is None


def test_active_signal_in_the_first_snapshot_starts_an_orphaned_event_at_service_start() -> None:
    started = events_only(feed(build_tank(), 1, dispense=True, value_kg=500))

    assert started == [
        StartedEvent(
            event_id=event_id(1),
            tank_id=3,
            kind=EventKind.DISPENSE,
            start_wall_ns=SERVICE_START_WALL_NS,
            start_value_kg=None,
            start_quality=StartQuality.UNKNOWN,
        )
    ]


def test_orphaned_event_closes_with_unknown_start_the_end_value_and_no_duration() -> None:
    tank = build_tank()
    feed(tank, 1, dispense=True)

    closed = events_only(feed(tank, 8, value_kg=250))

    assert closed == [
        ClosedEvent(
            event_id=event_id(1),
            tank_id=3,
            kind=EventKind.DISPENSE,
            start_wall_ns=SERVICE_START_WALL_NS,
            start_value_kg=None,
            end_wall_ns=2_008 * NS_PER_S,
            end_value_kg=250,
            duration_ns=None,
            start_quality=StartQuality.UNKNOWN,
            end_quality=EndQuality.FRESH,
        )
    ]


def test_orphaned_event_with_stale_end_records_both_qualities() -> None:
    tank = build_tank()
    feed(tank, 1, dispense=True)

    closed = events_only(feed(tank, 8, value_kg=None))

    assert isinstance(closed[0], ClosedEvent)
    assert (closed[0].start_quality, closed[0].end_quality) == ("unknown", "stale_reading")
    assert closed[0].end_value_kg is None


def test_orphaned_event_continues_while_the_signal_stays_active() -> None:
    tank = build_tank()
    feed(tank, 1, dispense=True)

    assert feed(tank, 2, dispense=True) == []


def test_loss_closes_an_event_in_progress_as_signal_lost_at_the_last_fresh_snapshot() -> None:
    tank = build_tank()
    feed(tank, 1)
    feed(tank, 2, dispense=True, value_kg=500)

    closed = tank.on_signals_lost(2_004 * NS_PER_S, 4 * NS_PER_S)

    assert closed == [
        ClosedEvent(
            event_id=event_id(1),
            tank_id=3,
            kind=EventKind.DISPENSE,
            start_wall_ns=2_002 * NS_PER_S,
            start_value_kg=500,
            end_wall_ns=2_004 * NS_PER_S,
            end_value_kg=None,
            duration_ns=2 * NS_PER_S,
            start_quality=StartQuality.FRESH,
            end_quality=EndQuality.SIGNAL_LOST,
        )
    ]


def test_loss_in_progress_with_stale_start_records_both_qualities() -> None:
    tank = build_tank()
    feed(tank, 1)
    feed(tank, 2, dispense=True, value_kg=None)

    closed = tank.on_signals_lost(2_004 * NS_PER_S, 4 * NS_PER_S)

    assert (closed[0].start_quality, closed[0].end_quality) == ("stale_reading", "signal_lost")


def test_loss_closes_an_orphaned_event_as_signal_lost_with_unknown_start() -> None:
    tank = build_tank()
    feed(tank, 1, dispense=True)

    closed = tank.on_signals_lost(2_004 * NS_PER_S, 4 * NS_PER_S)

    assert closed == [
        ClosedEvent(
            event_id=event_id(1),
            tank_id=3,
            kind=EventKind.DISPENSE,
            start_wall_ns=SERVICE_START_WALL_NS,
            start_value_kg=None,
            end_wall_ns=2_004 * NS_PER_S,
            end_value_kg=None,
            duration_ns=None,
            start_quality=StartQuality.UNKNOWN,
            end_quality=EndQuality.SIGNAL_LOST,
        )
    ]


def test_loss_with_an_event_of_zero_duration_gives_zero_duration() -> None:
    tank = build_tank()
    feed(tank, 1)
    feed(tank, 2, dispense=True)

    closed = tank.on_signals_lost(2_002 * NS_PER_S, 2 * NS_PER_S)

    assert closed[0].duration_ns == 0


def test_loss_closes_both_signals_dispense_first() -> None:
    tank = build_tank()
    feed(tank, 1)
    feed(tank, 2, dispense=True, refill=True)

    closed = tank.on_signals_lost(2_004 * NS_PER_S, 4 * NS_PER_S)

    assert [item.kind for item in closed] == ["dispense", "refill"]


def test_loss_without_open_events_closes_nothing() -> None:
    tank = build_tank()
    feed(tank, 1)

    assert tank.on_signals_lost(2_004 * NS_PER_S, 4 * NS_PER_S) == []


def test_after_loss_the_next_snapshot_reports_unknown_previous_states() -> None:
    tank = build_tank()
    feed(tank, 1, dispense=True)
    tank.on_signals_lost(2_004 * NS_PER_S, 4 * NS_PER_S)

    outputs = feed(tank, 9, dispense=True)

    assert [item for item in outputs if isinstance(item, SignalChange)] == [
        SignalChange(tank_id=3, signal=EventKind.DISPENSE, active=True, previous=None),
        SignalChange(tank_id=3, signal=EventKind.REFILL, active=False, previous=None),
    ]


def test_active_signal_after_loss_starts_an_orphaned_event_at_the_last_fresh_snapshot() -> None:
    tank = build_tank()
    feed(tank, 1)
    feed(tank, 2, dispense=True)
    tank.on_signals_lost(2_004 * NS_PER_S, 4 * NS_PER_S)

    started = events_only(feed(tank, 9, dispense=True, value_kg=400))

    assert started == [
        StartedEvent(
            event_id=event_id(2),
            tank_id=3,
            kind=EventKind.DISPENSE,
            start_wall_ns=2_004 * NS_PER_S,
            start_value_kg=None,
            start_quality=StartQuality.UNKNOWN,
        )
    ]


def test_inactive_signal_after_loss_starts_no_event() -> None:
    tank = build_tank()
    feed(tank, 1, dispense=True)
    tank.on_signals_lost(2_004 * NS_PER_S, 4 * NS_PER_S)

    assert events_only(feed(tank, 9)) == []


def test_after_loss_without_signals_the_orphaned_start_is_the_service_start() -> None:
    tank = build_tank()
    tank.on_signals_lost(SERVICE_START_WALL_NS, 0)

    started = events_only(feed(tank, 9, dispense=True))

    assert started[0].start_wall_ns == SERVICE_START_WALL_NS


def test_skipped_snapshot_puts_the_change_at_the_next_snapshot() -> None:
    tank = build_tank()
    feed(tank, 1)

    started = events_only(feed(tank, 4, dispense=True, value_kg=450))

    assert started[0].start_wall_ns == 2_004 * NS_PER_S
    assert started[0].start_value_kg == 450


def test_dispense_and_refill_overlap_on_one_tank_independently() -> None:
    tank = build_tank()
    feed(tank, 1)
    feed(tank, 2, dispense=True, value_kg=500)
    feed(tank, 3, dispense=True, refill=True, value_kg=480)

    closed_dispense = events_only(feed(tank, 4, refill=True, value_kg=470))
    closed_refill = events_only(feed(tank, 5, value_kg=600))

    assert [(item.kind, item.event_id) for item in closed_dispense] == [("dispense", event_id(1))]
    assert [(item.kind, item.event_id) for item in closed_refill] == [("refill", event_id(2))]


def test_shutdown_closes_an_event_in_progress_as_service_stopped_at_the_last_snapshot() -> None:
    tank = build_tank()
    feed(tank, 1)
    feed(tank, 2, dispense=True, value_kg=500)

    closed = tank.on_shutdown(2_004 * NS_PER_S, 4 * NS_PER_S)

    assert closed == [
        ClosedEvent(
            event_id=event_id(1),
            tank_id=3,
            kind=EventKind.DISPENSE,
            start_wall_ns=2_002 * NS_PER_S,
            start_value_kg=500,
            end_wall_ns=2_004 * NS_PER_S,
            end_value_kg=None,
            duration_ns=2 * NS_PER_S,
            start_quality=StartQuality.FRESH,
            end_quality=EndQuality.SERVICE_STOPPED,
        )
    ]


def test_shutdown_closes_an_orphaned_event_without_duration() -> None:
    tank = build_tank()
    feed(tank, 1, dispense=True)

    closed = tank.on_shutdown(2_004 * NS_PER_S, 4 * NS_PER_S)

    assert (closed[0].start_quality, closed[0].end_quality) == ("unknown", "service_stopped")
    assert (closed[0].start_wall_ns, closed[0].duration_ns) == (SERVICE_START_WALL_NS, None)


def test_shutdown_closes_both_signals_dispense_first() -> None:
    tank = build_tank()
    feed(tank, 1)
    feed(tank, 2, dispense=True, refill=True)

    closed = tank.on_shutdown(2_004 * NS_PER_S, 4 * NS_PER_S)

    assert [item.kind for item in closed] == ["dispense", "refill"]


def test_shutdown_without_open_events_closes_nothing() -> None:
    tank = build_tank()
    feed(tank, 1)

    assert tank.on_shutdown(2_004 * NS_PER_S, 4 * NS_PER_S) == []


def test_shutdown_after_loss_closes_nothing() -> None:
    tank = build_tank()
    feed(tank, 1)
    feed(tank, 2, dispense=True)
    tank.on_signals_lost(2_004 * NS_PER_S, 4 * NS_PER_S)

    assert tank.on_shutdown(2_004 * NS_PER_S, 4 * NS_PER_S) == []
