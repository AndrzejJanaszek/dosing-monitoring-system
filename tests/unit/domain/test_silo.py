from collections.abc import Sequence
from uuid import UUID

from dms.domain.events import ClosedEvent, EndQuality, EventKind, StartedEvent, StartQuality
from dms.domain.records import MeterRecord
from dms.domain.tank import SignalChange
from dms.messages import MeterReading, SignalStates, TankSignals, Tick
from dms.units import NS_PER_S
from tests.unit.domain.builders import build_silo


def reading(mono_s: float, value_kg: int) -> MeterReading:
    mono_ns = round(mono_s * NS_PER_S)
    return MeterReading(meter_id="m1", value_kg=value_kg, wall_ns=mono_ns + 1000, mono_ns=mono_ns)


def tick(mono_s: float) -> Tick:
    return Tick(0, round(mono_s * NS_PER_S))


def test_fresh_reading_gives_record_with_reading_timestamp() -> None:
    silo = build_silo(3)
    silo.on_reading(reading(10.0, 500))

    assert silo.on_tick(tick(10.4)) == [MeterRecord(3, 10 * NS_PER_S + 1000, 500)]


def test_no_reading_gives_no_record() -> None:
    assert build_silo(1).on_tick(tick(1)) == []


def test_stale_reading_gives_no_record() -> None:
    silo = build_silo(1)
    silo.on_reading(reading(10.0, 500))

    assert silo.on_tick(tick(11.5)) == []


def test_reading_exactly_at_age_limit_is_still_fresh() -> None:
    silo = build_silo(1)
    silo.on_reading(reading(10.0, 500))

    assert len(silo.on_tick(tick(11.0))) == 1


def test_same_reading_is_not_emitted_twice() -> None:
    silo = build_silo(1)
    silo.on_reading(reading(10.0, 500))

    assert len(silo.on_tick(tick(10.2))) == 1
    assert silo.on_tick(tick(10.8)) == []


def test_new_reading_after_emission_is_emitted() -> None:
    silo = build_silo(1)
    silo.on_reading(reading(10.0, 500))
    silo.on_tick(tick(10.2))
    silo.on_reading(reading(10.9, 520))

    assert silo.on_tick(tick(11.0)) == [MeterRecord(1, 10_900_001_000, 520)]


def test_tick_uses_the_latest_reading_when_several_arrived() -> None:
    silo = build_silo(1)
    for index, mono_s in enumerate((10.1, 10.3, 10.5)):
        silo.on_reading(reading(mono_s, 100 + index))

    (record,) = silo.on_tick(tick(10.6))

    assert isinstance(record, MeterRecord)
    assert record.value_kg == 102


def test_silo_is_not_stale_before_any_reading() -> None:
    silo = build_silo(1)
    silo.on_tick(tick(1))

    assert silo.stale_since_mono_ns is None


def test_stale_since_is_when_the_last_reading_crossed_the_age_limit() -> None:
    silo = build_silo(1)
    silo.on_reading(reading(10.0, 500))
    silo.on_tick(tick(11.5))
    silo.on_tick(tick(12.5))

    assert silo.stale_since_mono_ns == 11 * NS_PER_S


def test_fresh_reading_clears_stale_state() -> None:
    silo = build_silo(1)
    silo.on_reading(reading(10.0, 500))
    silo.on_tick(tick(11.5))
    silo.on_reading(reading(12.0, 510))
    silo.on_tick(tick(12.2))

    assert silo.stale_since_mono_ns is None


def test_signals_of_other_silos_tanks_are_skipped() -> None:
    silo = build_silo(1, tank_ids=(1,))
    states = SignalStates(
        (TankSignals(1, dispense=True, refill=False), TankSignals(2, dispense=True, refill=True)),
        0,
        0,
    )

    assert [item for item in silo.on_signals(states) if isinstance(item, SignalChange)] == [
        SignalChange(tank_id=1, signal=EventKind.DISPENSE, active=True, previous=None),
        SignalChange(tank_id=1, signal=EventKind.REFILL, active=False, previous=None),
    ]


def test_silo_without_tanks_reports_no_signal_changes() -> None:
    states = SignalStates((TankSignals(1, dispense=True, refill=True),), 0, 0)

    assert build_silo(1).on_signals(states) == []


def signals_at(mono_s: float, *, dispense: bool = False, refill: bool = False) -> SignalStates:
    mono_ns = round(mono_s * NS_PER_S)
    return SignalStates(
        (TankSignals(1, dispense=dispense, refill=refill),), 1_000 * NS_PER_S + mono_ns, mono_ns
    )


def only_events(outputs: Sequence[object]) -> list[StartedEvent | ClosedEvent]:
    return [item for item in outputs if isinstance(item, StartedEvent | ClosedEvent)]


def test_event_value_is_the_latest_fresh_reading_not_after_the_snapshot() -> None:
    silo = build_silo(1, tank_ids=(1,))
    silo.on_signals(signals_at(9.9))
    silo.on_reading(reading(10.0, 500))
    silo.on_reading(reading(10.3, 480))

    (started,) = only_events(silo.on_signals(signals_at(10.2, dispense=True)))

    assert isinstance(started, StartedEvent)
    assert started.start_value_kg == 500


def test_reading_exactly_at_the_snapshot_time_counts() -> None:
    silo = build_silo(1, tank_ids=(1,))
    silo.on_signals(signals_at(9.0))
    silo.on_reading(reading(10.0, 500))

    (started,) = only_events(silo.on_signals(signals_at(10.0, dispense=True)))

    assert isinstance(started, StartedEvent)
    assert started.start_value_kg == 500


def test_reading_older_than_the_age_limit_gives_no_event_value() -> None:
    silo = build_silo(1, tank_ids=(1,))
    silo.on_signals(signals_at(9.0))
    silo.on_reading(reading(10.0, 500))

    (started,) = only_events(silo.on_signals(signals_at(11.5, dispense=True)))

    assert isinstance(started, StartedEvent)
    assert started.start_value_kg is None


def test_silo_without_any_reading_gives_no_event_value() -> None:
    silo = build_silo(1, tank_ids=(1,))
    silo.on_signals(signals_at(1.0))

    (started,) = only_events(silo.on_signals(signals_at(2.0, dispense=True)))

    assert isinstance(started, StartedEvent)
    assert started.start_value_kg is None


def test_snapshot_stamped_before_the_last_tick_still_finds_its_reading() -> None:
    silo = build_silo(1, tank_ids=(1,))
    silo.on_signals(signals_at(10.1))
    silo.on_reading(reading(10.0, 500))
    silo.on_reading(reading(10.8, 480))
    silo.on_tick(tick(11.0))

    (started,) = only_events(silo.on_signals(signals_at(10.2, dispense=True)))

    assert isinstance(started, StartedEvent)
    assert started.start_value_kg == 500


def test_event_ids_come_from_the_injected_factory() -> None:
    silo = build_silo(1, tank_ids=(1,), new_event_id=lambda: UUID(int=42))
    silo.on_signals(signals_at(1.0))

    (started,) = only_events(silo.on_signals(signals_at(2.0, dispense=True)))

    assert isinstance(started, StartedEvent)
    assert started.event_id == UUID(int=42)


def test_signals_are_fresh_within_the_age_limit_of_the_last_snapshot() -> None:
    silo = build_silo(1, tank_ids=(1,))
    silo.on_signals(signals_at(10.0))

    assert silo.on_tick(tick(11.0)) == []
    assert silo.signals_stale_since_mono_ns is None


def test_lost_signals_close_the_open_event_at_the_last_fresh_snapshot() -> None:
    silo = build_silo(1, tank_ids=(1,))
    silo.on_signals(signals_at(9.0))
    silo.on_reading(reading(10.0, 500))
    silo.on_signals(signals_at(10.0, dispense=True))
    silo.on_signals(signals_at(10.25, dispense=True))

    closed = silo.on_tick(tick(11.5))

    assert closed == [
        ClosedEvent(
            event_id=UUID(int=1),
            tank_id=1,
            kind=EventKind.DISPENSE,
            start_wall_ns=1_010 * NS_PER_S,
            start_value_kg=500,
            end_wall_ns=1_000 * NS_PER_S + 10_250_000_000,
            end_value_kg=None,
            duration_ns=250_000_000,
            start_quality=StartQuality.FRESH,
            end_quality=EndQuality.SIGNAL_LOST,
        )
    ]
    assert silo.signals_stale_since_mono_ns == round(11.25 * NS_PER_S)


def test_lost_signals_are_handled_once() -> None:
    silo = build_silo(1, tank_ids=(1,))
    silo.on_signals(signals_at(9.0))
    silo.on_signals(signals_at(10.0, dispense=True))
    silo.on_tick(tick(12.0))

    assert silo.on_tick(tick(13.0)) == []


def test_lost_signals_are_detected_even_when_the_meter_is_silent() -> None:
    silo = build_silo(1, tank_ids=(1,))
    silo.on_signals(signals_at(9.0))
    silo.on_reading(reading(10.0, 500))
    silo.on_signals(signals_at(10.0, dispense=True))

    closed = silo.on_tick(tick(20.0))

    assert [item.end_quality for item in closed if isinstance(item, ClosedEvent)] == [
        "signal_lost"
    ]


def test_snapshot_ends_the_stale_signals_state() -> None:
    silo = build_silo(1, tank_ids=(1,))
    silo.on_signals(signals_at(9.0))
    silo.on_tick(tick(12.0))

    silo.on_signals(signals_at(13.0))

    assert silo.signals_stale_since_mono_ns is None


def test_active_signal_after_lost_signals_starts_an_orphaned_event() -> None:
    silo = build_silo(1, tank_ids=(1,))
    silo.on_signals(signals_at(9.0))
    silo.on_tick(tick(12.0))

    (started,) = only_events(silo.on_signals(signals_at(13.0, dispense=True)))

    assert isinstance(started, StartedEvent)
    assert (started.start_quality, started.start_wall_ns) == ("unknown", 1_009 * NS_PER_S)


def test_signals_that_never_arrived_are_stale_from_the_service_start() -> None:
    silo = build_silo(1, tank_ids=(1,), started_mono_ns=5 * NS_PER_S)

    assert silo.on_tick(tick(5.5)) == []
    assert silo.signals_stale_since_mono_ns is None

    assert silo.on_tick(tick(6.5)) == []
    assert silo.signals_stale_since_mono_ns == 6 * NS_PER_S


def test_orphaned_start_after_a_silent_start_is_the_service_start() -> None:
    silo = build_silo(1, tank_ids=(1,), started_wall_ns=777)
    silo.on_tick(tick(3.0))

    (started,) = only_events(silo.on_signals(signals_at(4.0, dispense=True)))

    assert isinstance(started, StartedEvent)
    assert started.start_wall_ns == 777


def test_silo_without_tanks_never_reports_stale_signals() -> None:
    silo = build_silo(1)

    assert silo.on_tick(tick(100.0)) == []
    assert silo.signals_stale_since_mono_ns is None


def test_shutdown_closes_the_open_event_at_the_last_snapshot() -> None:
    silo = build_silo(1, tank_ids=(1,))
    silo.on_signals(signals_at(9.0))
    silo.on_reading(reading(10.0, 500))
    silo.on_signals(signals_at(10.0, dispense=True))
    silo.on_signals(signals_at(10.25, dispense=True))

    closed = silo.on_shutdown()

    assert closed == [
        ClosedEvent(
            event_id=UUID(int=1),
            tank_id=1,
            kind=EventKind.DISPENSE,
            start_wall_ns=1_010 * NS_PER_S,
            start_value_kg=500,
            end_wall_ns=1_000 * NS_PER_S + 10_250_000_000,
            end_value_kg=None,
            duration_ns=250_000_000,
            start_quality=StartQuality.FRESH,
            end_quality=EndQuality.SERVICE_STOPPED,
        )
    ]


def test_shutdown_before_any_snapshot_closes_nothing() -> None:
    assert build_silo(1, tank_ids=(1,)).on_shutdown() == []


def test_shutdown_after_lost_signals_closes_nothing() -> None:
    silo = build_silo(1, tank_ids=(1,))
    silo.on_signals(signals_at(9.0))
    silo.on_signals(signals_at(10.0, dispense=True))
    silo.on_tick(tick(12.0))

    assert silo.on_shutdown() == []


def test_silo_without_tanks_closes_nothing_on_shutdown() -> None:
    assert build_silo(1).on_shutdown() == []
