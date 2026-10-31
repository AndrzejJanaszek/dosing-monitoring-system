import itertools
import queue
import threading
from collections.abc import Callable, Iterable
from pathlib import Path
from uuid import UUID

import pytest

from dms.acquisition.app import board_wiring, build_silos, meter_wiring
from dms.acquisition.engine import Engine
from dms.acquisition.serial.adapter import FrameHandler
from dms.acquisition.serial.framing import Framer
from dms.domain.events import EndQuality, EventKind, StartedEvent, StartQuality
from dms.domain.records import EventRecord, WriterRecord
from dms.messages import EngineMessage, Tick
from dms.simulator.catalog import OTHER_TANK_SUFFIX, RELATIONS, SCENARIOS
from dms.simulator.dms_config import acquisition_config
from dms.simulator.encoders import encode_banner, encode_sample
from dms.simulator.expected_events import ExpectedEvent, expected_events
from dms.simulator.scenario import Scenario
from dms.simulator.timeline import MeterSample, PinsSample, Sample, samples_from, scenario_samples
from dms.units import NS_PER_S

MAX_READING_AGE_NS = NS_PER_S
MAX_SIGNAL_AGE_NS = NS_PER_S
TICK_INTERVAL_NS = NS_PER_S
STALE_GAP_NS = round(1.2 * NS_PER_S)
SIGNAL_GAP_NS = 5 * NS_PER_S


def counting_ids() -> Callable[[], UUID]:
    numbers = itertools.count(1)
    return lambda: UUID(int=next(numbers))


def run_pipeline(
    scenario: Scenario, samples: Iterable[Sample], tmp_path: Path
) -> list[WriterRecord]:
    config = acquisition_config(scenario.layout, tmp_path)
    assert config.board is not None
    messages: queue.Queue[EngineMessage] = queue.Queue()
    writer_queue: queue.Queue[WriterRecord] = queue.Queue()
    engine = Engine(
        in_queue=queue.Queue(),
        out_queue=writer_queue,
        silos_by_meter=build_silos(
            config, new_event_id=counting_ids(), started_wall_ns=0, started_mono_ns=0
        ),
        stop_event=threading.Event(),
    )
    board = config.board
    ports: dict[str, tuple[Framer, FrameHandler]] = {
        meter.id: meter_wiring(meter, messages) for meter in config.meters
    }
    ports[board.id] = board_wiring(board, config.tanks, messages)

    board_framer, board_handler = ports[board.id]
    for frame in board_framer.feed(encode_banner(scenario.layout.board)):
        board_handler.handle(frame, 0, 0)

    next_tick_ns = 0
    last_at_ns = 0
    for sample in samples:
        while next_tick_ns < sample.at_ns:
            engine.handle(Tick(next_tick_ns, next_tick_ns))
            next_tick_ns += TICK_INTERVAL_NS
        device_id, data = encode_sample(sample, scenario.layout)
        framer, handler = ports[device_id]
        for frame in framer.feed(data):
            handler.handle(frame, sample.at_ns, sample.at_ns)
        while not messages.empty():
            engine.handle(messages.get_nowait())
        last_at_ns = sample.at_ns
    while next_tick_ns <= last_at_ns:
        engine.handle(Tick(next_tick_ns, next_tick_ns))
        next_tick_ns += TICK_INTERVAL_NS

    records: list[WriterRecord] = []
    while not writer_queue.empty():
        records.append(writer_queue.get_nowait())
    return records


def closed_events(records: list[WriterRecord]) -> list[EventRecord]:
    return [record for record in records if isinstance(record, EventRecord)]


def as_expected(record: EventRecord) -> ExpectedEvent:
    event = record.event
    return ExpectedEvent(
        tank_id=event.tank_id,
        kind=event.kind,
        start_ns=event.start_wall_ns,
        end_ns=event.end_wall_ns,
        start_value_kg=event.start_value_kg,
        end_value_kg=event.end_value_kg,
        start_quality=event.start_quality,
        end_quality=event.end_quality,
        collision=record.collision,
        rule_violation=record.rule_violation,
    )


def is_fresh(event: ExpectedEvent) -> bool:
    return (event.start_quality, event.end_quality) == (StartQuality.FRESH, EndQuality.FRESH)


def ordered(events: list[ExpectedEvent]) -> list[ExpectedEvent]:
    return sorted(events, key=lambda event: (event.end_ns, event.tank_id, event.kind))


def system_events(records: list[WriterRecord]) -> list[ExpectedEvent]:
    return ordered([as_expected(event) for event in closed_events(records)])


def oracle_events(
    scenario: Scenario, samples: list[Sample], start_ns: int = 0
) -> list[ExpectedEvent]:
    return ordered(
        expected_events(
            scenario, samples, max_reading_age_ns=MAX_READING_AGE_NS, start_ns=start_ns
        )
    )


def assert_every_close_follows_its_start(records: list[WriterRecord]) -> None:
    started: dict[UUID, StartedEvent] = {}
    for record in records:
        if isinstance(record, StartedEvent):
            assert record.event_id not in started
            started[record.event_id] = record
        elif isinstance(record, EventRecord):
            event = record.event
            opened = started[event.event_id]
            assert (opened.tank_id, opened.kind) == (event.tank_id, event.kind)
            assert opened.start_wall_ns == event.start_wall_ns
            assert opened.start_value_kg == event.start_value_kg


def without_meter_samples(samples: list[Sample], meter_id: str, around_ns: int) -> list[Sample]:
    return [
        sample
        for sample in samples
        if not (
            isinstance(sample, MeterSample)
            and sample.meter_id == meter_id
            and around_ns - STALE_GAP_NS <= sample.at_ns <= around_ns
        )
    ]


@pytest.mark.parametrize("scenario", SCENARIOS.values(), ids=list(SCENARIOS))
def test_events_of_every_catalogue_scenario_match_the_oracle(
    scenario: Scenario, tmp_path: Path
) -> None:
    samples = list(scenario_samples(scenario))

    records = run_pipeline(scenario, samples, tmp_path)

    expected = oracle_events(scenario, samples)
    assert system_events(records) == expected
    assert len(expected) == len(scenario.events)
    assert all(is_fresh(event) for event in expected)
    assert all(
        event.start_value_kg is not None and event.end_value_kg is not None for event in expected
    )
    assert_every_close_follows_its_start(records)
    assert not [
        r
        for r in records
        if isinstance(r, StartedEvent) and r.start_quality is StartQuality.UNKNOWN
    ]


COLLISION_FREE_RELATIONS = {
    "dispense-before-refill",
    "dispense-after-refill",
    "dispense-meets-refill",
    "refill-meets-dispense",
}
RELATION_NAMES = {relation.name for relation in RELATIONS}
RELATION_SCENARIOS = [
    name for name in SCENARIOS if name.removesuffix(OTHER_TANK_SUFFIX) in RELATION_NAMES
]


def flags_by_kind(events: list[ExpectedEvent]) -> set[tuple[EventKind, bool, bool]]:
    return {(event.kind, event.collision, event.rule_violation) for event in events}


@pytest.mark.parametrize("name", RELATION_SCENARIOS)
def test_dispense_and_refill_collide_only_when_they_overlap(name: str, tmp_path: Path) -> None:
    scenario = SCENARIOS[name]
    samples = list(scenario_samples(scenario))

    events = system_events(run_pipeline(scenario, samples, tmp_path))

    collision = name.removesuffix(OTHER_TANK_SUFFIX) not in COLLISION_FREE_RELATIONS
    assert flags_by_kind(events) == {
        (EventKind.DISPENSE, collision, False),
        (EventKind.REFILL, collision, False),
    }


def test_dispenses_on_both_tanks_flag_both_events_as_rule_violations(tmp_path: Path) -> None:
    scenario = SCENARIOS["dispense-both-tanks-concurrent"]
    samples = list(scenario_samples(scenario))

    events = system_events(run_pipeline(scenario, samples, tmp_path))

    assert [(event.tank_id, event.collision, event.rule_violation) for event in events] == [
        (1, True, True),
        (2, True, True),
    ]


def test_refill_with_concurrent_dispenses_collides_without_its_own_rule_violation(
    tmp_path: Path,
) -> None:
    scenario = SCENARIOS["refill-with-concurrent-dispenses-both-tanks"]
    samples = list(scenario_samples(scenario))

    events = system_events(run_pipeline(scenario, samples, tmp_path))

    assert sorted((event.kind, event.tank_id, event.rule_violation) for event in events) == [
        (EventKind.DISPENSE, 1, True),
        (EventKind.DISPENSE, 2, True),
        (EventKind.REFILL, 1, False),
    ]
    assert all(event.collision for event in events)


def test_refill_overlapping_a_dispense_with_an_unknown_start_is_a_collision(
    tmp_path: Path,
) -> None:
    scenario = SCENARIOS["dispense-front-refill"]
    offset_ns = 95 * NS_PER_S
    samples = list(
        itertools.takewhile(
            lambda sample: sample.at_ns <= scenario.duration_ns - offset_ns,
            samples_from(scenario, 0, lambda t_ns: t_ns + offset_ns),
        )
    )

    records = run_pipeline(scenario, samples, tmp_path)

    dispense, refill = system_events(records)
    assert system_events(records) == oracle_events(scenario, samples)
    assert (dispense.kind, dispense.start_quality, dispense.collision) == (
        EventKind.DISPENSE,
        StartQuality.UNKNOWN,
        True,
    )
    assert (refill.kind, refill.start_quality, refill.collision) == (
        EventKind.REFILL,
        StartQuality.FRESH,
        True,
    )


def test_service_started_in_the_middle_of_an_event_gives_an_unknown_start_event(
    tmp_path: Path,
) -> None:
    scenario = SCENARIOS["dispense-series"]
    offset_ns = 15 * NS_PER_S
    samples = list(
        itertools.takewhile(
            lambda sample: sample.at_ns <= scenario.duration_ns - offset_ns,
            samples_from(scenario, 0, lambda t_ns: t_ns + offset_ns),
        )
    )

    records = run_pipeline(scenario, samples, tmp_path)

    expected = oracle_events(scenario, samples)
    assert system_events(records) == expected
    first, *rest = expected
    assert (first.start_ns, first.start_quality, first.start_value_kg) == (
        0,
        StartQuality.UNKNOWN,
        None,
    )
    assert first.end_quality is EndQuality.FRESH
    assert first.end_value_kg is not None
    assert len(rest) == 2
    assert all(is_fresh(event) for event in rest)
    orphaned = [
        r
        for r in records
        if isinstance(r, StartedEvent) and r.start_quality is StartQuality.UNKNOWN
    ]
    assert [(r.start_wall_ns, r.start_value_kg) for r in orphaned] == [(0, None)]
    assert_every_close_follows_its_start(records)


@pytest.mark.parametrize(
    ("edge", "qualities", "empty_value"),
    [
        ("start", (StartQuality.STALE_READING, EndQuality.FRESH), "start_value_kg"),
        ("end", (StartQuality.FRESH, EndQuality.STALE_READING), "end_value_kg"),
    ],
)
def test_missing_meter_samples_at_an_edge_give_an_incomplete_event(
    edge: str, qualities: tuple[StartQuality, EndQuality], empty_value: str, tmp_path: Path
) -> None:
    scenario = SCENARIOS["dispense-single"]
    clean_samples = list(scenario_samples(scenario))
    (clean,) = oracle_events(scenario, clean_samples)
    edge_ns = clean.start_ns if edge == "start" else clean.end_ns
    samples = without_meter_samples(clean_samples, "meter-1", edge_ns)

    records = run_pipeline(scenario, samples, tmp_path)

    (event,) = system_events(records)
    assert event == oracle_events(scenario, samples)[0]
    assert (event.start_quality, event.end_quality) == qualities
    assert getattr(event, empty_value) is None
    assert (event.start_ns, event.end_ns) == (clean.start_ns, clean.end_ns)
    assert_every_close_follows_its_start(records)


def test_missing_meter_samples_at_both_edges_report_both_stale_edges(tmp_path: Path) -> None:
    scenario = SCENARIOS["dispense-single"]
    clean_samples = list(scenario_samples(scenario))
    (clean,) = oracle_events(scenario, clean_samples)
    samples = without_meter_samples(clean_samples, "meter-1", clean.start_ns)
    samples = without_meter_samples(samples, "meter-1", clean.end_ns)

    records = run_pipeline(scenario, samples, tmp_path)

    (event,) = system_events(records)
    assert event == oracle_events(scenario, samples)[0]
    assert (event.start_quality, event.end_quality) == (
        StartQuality.STALE_READING,
        EndQuality.STALE_READING,
    )
    assert (event.start_value_kg, event.end_value_kg) == (None, None)


def test_lost_signals_in_the_middle_of_an_event_end_it_and_orphan_the_rest(
    tmp_path: Path,
) -> None:
    scenario = SCENARIOS["dispense-single"]
    clean_samples = list(scenario_samples(scenario))
    (clean,) = oracle_events(scenario, clean_samples)
    gap_start_ns = clean.start_ns + 5 * NS_PER_S
    gap_end_ns = gap_start_ns + SIGNAL_GAP_NS
    samples = [
        sample
        for sample in clean_samples
        if not (isinstance(sample, PinsSample) and gap_start_ns < sample.at_ns < gap_end_ns)
    ]
    last_fresh_ns = max(
        sample.at_ns
        for sample in samples
        if isinstance(sample, PinsSample) and sample.at_ns <= gap_start_ns
    )

    records = run_pipeline(scenario, samples, tmp_path)

    lost, orphaned = system_events(records)
    assert lost == ExpectedEvent(
        tank_id=1,
        kind=EventKind.DISPENSE,
        start_ns=clean.start_ns,
        end_ns=last_fresh_ns,
        start_value_kg=clean.start_value_kg,
        end_value_kg=None,
        start_quality=StartQuality.FRESH,
        end_quality=EndQuality.SIGNAL_LOST,
        collision=False,
        rule_violation=False,
    )
    assert orphaned == ExpectedEvent(
        tank_id=1,
        kind=EventKind.DISPENSE,
        start_ns=last_fresh_ns,
        end_ns=clean.end_ns,
        start_value_kg=None,
        end_value_kg=clean.end_value_kg,
        start_quality=StartQuality.UNKNOWN,
        end_quality=EndQuality.FRESH,
        collision=False,
        rule_violation=False,
    )
    assert_every_close_follows_its_start(records)
