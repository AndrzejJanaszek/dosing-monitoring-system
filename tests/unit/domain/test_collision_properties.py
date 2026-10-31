import itertools
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from hypothesis import given, settings
from hypothesis import strategies as st

from dms.domain.collisions import CollisionTracker, Overlap, RuleViolation
from dms.domain.events import EventKind, StartedEvent, StartQuality
from dms.domain.records import EventRecord
from dms.domain.silo import Silo
from dms.messages import SignalStates, TankSignals, Tick
from dms.units import NS_PER_S
from tests.unit.domain.builders import build_silo

TANK_IDS = (1, 2)
FRAME_STEP_NS = NS_PER_S // 2
LOST_TICK_DELAY_NS = 3 * NS_PER_S // 2
LOST = "lost"

PROPERTY_SETTINGS = settings(max_examples=200, derandomize=True, database=None, deadline=None)

tank_states = st.tuples(st.booleans(), st.booleans())
frames = st.tuples(*(tank_states for _ in TANK_IDS))
steps = st.lists(st.one_of(frames, st.just(LOST)), min_size=1, max_size=30)


@dataclass(frozen=True, slots=True, kw_only=True)
class Interval:
    event_id: UUID
    tank_id: int
    kind: EventKind
    start_ns: int
    end_ns: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Run:
    intervals: list[Interval]
    records: dict[UUID, EventRecord]
    violations: list[RuleViolation]


def frame_states(mono_ns: int, frame: tuple[tuple[bool, bool], ...]) -> SignalStates:
    return SignalStates(
        tuple(
            TankSignals(tank_id, dispense=dispense, refill=refill)
            for tank_id, (dispense, refill) in zip(TANK_IDS, frame, strict=True)
        ),
        mono_ns,
        mono_ns,
    )


class Recorder:
    def __init__(self) -> None:
        self.starts: dict[UUID, tuple[StartedEvent, int]] = {}
        self.ends: dict[UUID, tuple[EventRecord, int]] = {}
        self.violations: list[RuleViolation] = []

    def collect(self, outputs: Sequence[object], at_ns: int) -> None:
        for output in outputs:
            if isinstance(output, StartedEvent):
                self.starts[output.event_id] = (output, at_ns)
            elif isinstance(output, EventRecord):
                self.ends[output.event.event_id] = (output, at_ns)
            elif isinstance(output, RuleViolation):
                self.violations.append(output)

    def run(self) -> Run:
        intervals = [
            Interval(
                event_id=event_id,
                tank_id=started.tank_id,
                kind=started.kind,
                start_ns=start_ns,
                end_ns=self.ends[event_id][1],
            )
            for event_id, (started, start_ns) in self.starts.items()
        ]
        records = {event_id: record for event_id, (record, _) in self.ends.items()}
        return Run(intervals=intervals, records=records, violations=self.violations)


def drive(silo: Silo, plan: Sequence[tuple[tuple[bool, bool], ...] | str]) -> Run:
    recorder = Recorder()
    mono_ns = 0
    last_frame_ns = 0
    for step in plan:
        if isinstance(step, str):
            mono_ns = last_frame_ns + LOST_TICK_DELAY_NS
            recorder.collect(silo.on_tick(Tick(mono_ns, mono_ns)), last_frame_ns + 1)
        else:
            mono_ns += FRAME_STEP_NS
            last_frame_ns = mono_ns
            recorder.collect(silo.on_signals(frame_states(mono_ns, step)), mono_ns)
    recorder.collect(silo.on_shutdown(), last_frame_ns + 1)
    return recorder.run()


def intersect(first: Interval, second: Interval) -> bool:
    return first.start_ns < second.end_ns and second.start_ns < first.end_ns


def violates(first: Interval, second: Interval) -> bool:
    return (
        first.kind is second.kind and first.tank_id != second.tank_id and intersect(first, second)
    )


@PROPERTY_SETTINGS
@given(steps)
def test_flags_match_the_brute_force_intersection_of_event_intervals(
    plan: list[tuple[tuple[bool, bool], ...] | str],
) -> None:
    run = drive(build_silo(1, tank_ids=TANK_IDS), plan)

    for interval in run.intervals:
        others = [other for other in run.intervals if other.event_id != interval.event_id]
        record = run.records[interval.event_id]
        assert record.collision == any(intersect(interval, other) for other in others)
        assert record.rule_violation == any(violates(interval, other) for other in others)


@PROPERTY_SETTINGS
@given(steps)
def test_violations_are_reported_once_for_each_intersecting_pair_of_the_same_type(
    plan: list[tuple[tuple[bool, bool], ...] | str],
) -> None:
    run = drive(build_silo(1, tank_ids=TANK_IDS), plan)

    reported = [
        frozenset((violation.event_id, violation.other_event_id)) for violation in run.violations
    ]
    expected = {
        frozenset((first.event_id, second.event_id))
        for first, second in itertools.combinations(run.intervals, 2)
        if violates(first, second)
    }
    assert sorted(reported, key=sorted) == sorted(expected, key=sorted)


slot_sequences = st.lists(st.integers(min_value=0, max_value=3), min_size=1, max_size=40)


def started_event(event_number: int, slot: int) -> StartedEvent:
    return StartedEvent(
        event_id=UUID(int=event_number),
        tank_id=TANK_IDS[slot % 2],
        kind=EventKind.DISPENSE if slot < 2 else EventKind.REFILL,
        start_wall_ns=0,
        start_value_kg=None,
        start_quality=StartQuality.STALE_READING,
    )


@PROPERTY_SETTINGS
@given(slot_sequences, st.lists(st.booleans(), min_size=40, max_size=40))
def test_both_events_of_a_pair_see_the_same_overlap(
    slots: list[int], unknown_starts: list[bool]
) -> None:
    tracker = CollisionTracker(1)
    open_slots: dict[int, UUID] = {}
    seen: dict[UUID, list[Overlap]] = {}
    numbers = itertools.count(1)

    for mono_ns, slot in enumerate(slots):
        if slot in open_slots:
            event_id = open_slots.pop(slot)
            seen[event_id] = tracker.on_closed(event_id, mono_ns, edge_known=mono_ns % 3 != 0)
        else:
            event = started_event(next(numbers), slot)
            open_slots[slot] = event.event_id
            tracker.on_started(event, None if unknown_starts[mono_ns] else mono_ns)
    for event_id in open_slots.values():
        seen[event_id] = tracker.on_closed(event_id, len(slots), edge_known=False)

    for event_id, overlaps in seen.items():
        for overlap in overlaps:
            (mirror,) = [item for item in seen[overlap.partner_id] if item.partner_id == event_id]
            assert (mirror.start_mono_ns, mirror.end_mono_ns, mirror.end_known) == (
                overlap.start_mono_ns,
                overlap.end_mono_ns,
                overlap.end_known,
            )
