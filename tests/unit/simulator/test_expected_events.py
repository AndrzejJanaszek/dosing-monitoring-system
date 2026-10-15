from dms.simulator.expected_events import ExpectedEvent, expected_events
from dms.simulator.layout import PlantLayout, SiloLayout
from dms.simulator.timeline import MeterSample, PinsSample, Sample
from tests.unit.simulator.builders import dispense, scenario_with, tank

SECOND_NS = 1_000_000_000
MAX_AGE_NS = SECOND_NS


def pins(at_s: float, *, dispense_active: bool = False, refill_active: bool = False) -> PinsSample:
    return PinsSample(
        round(at_s * SECOND_NS),
        "arduino",
        ((4, 0 if dispense_active else 1), (5, 0 if refill_active else 1)),
    )


def meter(at_s: float, value_kg: int) -> MeterSample:
    return MeterSample(round(at_s * SECOND_NS), "meter-1", value_kg)


def events_from(samples: list[Sample], start_ns: int = 0) -> list[ExpectedEvent]:
    return expected_events(
        scenario_with(dispense()), samples, max_reading_age_ns=MAX_AGE_NS, start_ns=start_ns
    )


def test_completed_event_uses_the_latest_meter_samples_before_each_edge() -> None:
    samples: list[Sample] = [
        meter(0.0, 1000),
        pins(0.0),
        meter(1.0, 1000),
        pins(1.1, dispense_active=True),
        meter(1.2, 900),
        meter(2.0, 700),
        pins(2.1),
    ]

    assert events_from(samples) == [
        ExpectedEvent(1, "dispense", 1_100_000_000, 2_100_000_000, 1000, 700, "fresh", "fresh")
    ]


def test_meter_sample_after_the_edge_in_the_stream_is_not_used() -> None:
    samples: list[Sample] = [
        meter(0.0, 1000),
        pins(0.0),
        pins(1.0, dispense_active=True),
        meter(1.0, 900),
        meter(1.5, 800),
        pins(2.0),
        meter(2.0, 700),
    ]

    (event,) = events_from(samples)

    assert (event.start_value_kg, event.end_value_kg) == (1000, 800)


def test_meter_sample_with_the_same_time_before_the_edge_in_the_stream_is_used() -> None:
    samples: list[Sample] = [
        meter(0.0, 1000),
        pins(0.0),
        meter(1.0, 900),
        pins(1.0, dispense_active=True),
        meter(2.0, 700),
        pins(2.0),
    ]

    (event,) = events_from(samples)

    assert (event.start_value_kg, event.end_value_kg) == (900, 700)


def test_meter_sample_exactly_at_the_age_limit_is_fresh() -> None:
    samples: list[Sample] = [
        pins(0.0),
        meter(0.0, 1000),
        pins(1.0, dispense_active=True),
        pins(1.5),
    ]

    (event,) = events_from(samples)

    assert event.start_value_kg == 1000


def test_stale_start_reading_leaves_the_start_value_empty() -> None:
    samples: list[Sample] = [
        pins(0.0),
        meter(0.0, 1000),
        pins(1.5, dispense_active=True),
        meter(2.0, 800),
        pins(2.5),
    ]

    (event,) = events_from(samples)

    assert (event.start_value_kg, event.end_value_kg) == (None, 800)
    assert (event.start_quality, event.end_quality) == ("stale_reading", "fresh")


def test_stale_end_reading_leaves_the_end_value_empty() -> None:
    samples: list[Sample] = [
        meter(0.0, 1000),
        pins(0.0),
        pins(0.5, dispense_active=True),
        pins(3.0),
    ]

    (event,) = events_from(samples)

    assert (event.start_value_kg, event.end_value_kg) == (1000, None)
    assert (event.start_quality, event.end_quality) == ("fresh", "stale_reading")


def test_stale_start_and_stale_end_are_both_recorded() -> None:
    samples: list[Sample] = [pins(0.0), pins(1.0, dispense_active=True), pins(2.0)]

    (event,) = events_from(samples)

    assert (event.start_quality, event.end_quality) == ("stale_reading", "stale_reading")


def test_missing_meter_sample_counts_as_stale() -> None:
    samples: list[Sample] = [pins(0.0), pins(1.0, dispense_active=True), pins(2.0)]

    (event,) = events_from(samples)

    assert (event.start_value_kg, event.end_value_kg) == (None, None)


def test_active_signal_in_the_first_sample_gives_an_unknown_start_event() -> None:
    samples: list[Sample] = [
        meter(5.0, 1000),
        pins(5.0, dispense_active=True),
        meter(8.0, 700),
        pins(8.0),
    ]

    (event,) = events_from(samples, start_ns=5 * SECOND_NS)

    assert event == ExpectedEvent(
        1, "dispense", 5 * SECOND_NS, 8 * SECOND_NS, None, 700, "unknown", "fresh"
    )


def test_event_still_open_at_the_end_of_the_samples_is_not_reported() -> None:
    samples: list[Sample] = [meter(0.0, 1000), pins(0.0), pins(1.0, dispense_active=True)]

    assert events_from(samples) == []


def test_no_change_gives_no_events() -> None:
    assert events_from([meter(0.0, 1), pins(0.0), pins(1.0), pins(2.0)]) == []


def test_dispense_and_refill_of_one_tank_are_tracked_separately() -> None:
    samples: list[Sample] = [
        meter(0.0, 1000),
        pins(0.0),
        pins(1.0, dispense_active=True),
        meter(1.5, 900),
        pins(2.0, dispense_active=True, refill_active=True),
        pins(3.0, refill_active=True),
        pins(4.0),
    ]

    events = events_from(samples)

    assert [
        (item.kind, item.start_ns // SECOND_NS, item.end_ns // SECOND_NS) for item in events
    ] == [
        ("dispense", 1, 3),
        ("refill", 2, 4),
    ]


def test_active_level_of_the_wiring_is_respected() -> None:
    layout = PlantLayout((SiloLayout(1, (tank(1, 4, 5, active_level=1),)),))
    samples: list[Sample] = [
        meter(0.0, 1000),
        PinsSample(0, "arduino", ((4, 0), (5, 0))),
        PinsSample(SECOND_NS, "arduino", ((4, 1), (5, 0))),
        PinsSample(2 * SECOND_NS, "arduino", ((4, 0), (5, 0))),
    ]

    events = expected_events(
        scenario_with(dispense(), layout=layout), samples, max_reading_age_ns=MAX_AGE_NS
    )

    assert [(item.kind, item.tank_id) for item in events] == [("dispense", 1)]


def test_meters_of_different_silos_are_kept_apart() -> None:
    layout = PlantLayout((SiloLayout(1, (tank(1, 4, 5),)), SiloLayout(2, (tank(2, 6, 7),))))
    samples: list[Sample] = [
        MeterSample(0, "meter-1", 1000),
        MeterSample(0, "meter-2", 5000),
        PinsSample(0, "arduino", ((4, 1), (5, 1), (6, 1), (7, 1))),
        PinsSample(SECOND_NS, "arduino", ((4, 1), (5, 1), (6, 0), (7, 1))),
        PinsSample(2 * SECOND_NS, "arduino", ((4, 1), (5, 1), (6, 1), (7, 1))),
    ]

    (event,) = expected_events(
        scenario_with(dispense(tank_id=2), layout=layout), samples, max_reading_age_ns=MAX_AGE_NS
    )

    assert (event.tank_id, event.start_value_kg) == (2, 5000)
