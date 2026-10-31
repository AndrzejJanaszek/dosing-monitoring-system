import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass

from dms.domain.events import EndQuality, EventKind, StartQuality
from dms.simulator.layout import Input, PlantLayout
from dms.simulator.scenario import Scenario
from dms.simulator.timeline import MeterSample, PinsSample, Sample


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpectedEvent:
    tank_id: int
    kind: EventKind
    start_ns: int
    end_ns: int
    start_value_kg: int | None
    end_value_kg: int | None
    start_quality: StartQuality
    end_quality: EndQuality
    collision: bool
    rule_violation: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class _OpenEvent:
    start_ns: int
    start_value_kg: int | None
    start_quality: StartQuality


def expected_events(
    scenario: Scenario,
    samples: Sequence[Sample],
    *,
    max_reading_age_ns: int,
    start_ns: int = 0,
) -> list[ExpectedEvent]:
    latest_meter_samples: dict[str, MeterSample] = {}
    open_events: dict[tuple[int, EventKind], _OpenEvent | None] = {}
    expected: list[ExpectedEvent] = []
    first_pins_sample = True

    for sample in samples:
        if isinstance(sample, MeterSample):
            latest_meter_samples[sample.meter_id] = sample
        elif isinstance(sample, PinsSample):
            levels = dict(sample.levels)
            for silo in scenario.layout.silos:
                value_kg = _fresh_value_kg(
                    latest_meter_samples.get(silo.meter_id), sample.at_ns, max_reading_age_ns
                )
                for tank in silo.tanks:
                    for kind, wiring in _wirings(tank.dispense, tank.refill):
                        key = (tank.id, kind)
                        active = levels[wiring.pin] == wiring.active_level
                        expected.extend(
                            _step(
                                key,
                                open_events,
                                active=active,
                                first=first_pins_sample,
                                at_ns=sample.at_ns,
                                service_start_ns=start_ns,
                                value_kg=value_kg,
                            )
                        )
            first_pins_sample = False
    return _with_flags(scenario.layout, expected)


def _with_flags(layout: PlantLayout, events: list[ExpectedEvent]) -> list[ExpectedEvent]:
    flagged: list[ExpectedEvent] = []
    for event in events:
        overlapping = [
            other
            for other in events
            if other is not event
            and layout.silo_of(other.tank_id).id == layout.silo_of(event.tank_id).id
            and other.start_ns < event.end_ns
            and event.start_ns < other.end_ns
        ]
        flagged.append(
            dataclasses.replace(
                event,
                collision=bool(overlapping),
                rule_violation=any(other.kind is event.kind for other in overlapping),
            )
        )
    return flagged


def _wirings(dispense: Input, refill: Input) -> tuple[tuple[EventKind, Input], ...]:
    return ((EventKind.DISPENSE, dispense), (EventKind.REFILL, refill))


def _fresh_value_kg(
    meter_sample: MeterSample | None, at_ns: int, max_reading_age_ns: int
) -> int | None:
    if meter_sample is None or at_ns - meter_sample.at_ns > max_reading_age_ns:
        return None
    return meter_sample.value_kg


def _start_quality(value_kg: int | None) -> StartQuality:
    return StartQuality.STALE_READING if value_kg is None else StartQuality.FRESH


def _end_quality(value_kg: int | None) -> EndQuality:
    return EndQuality.STALE_READING if value_kg is None else EndQuality.FRESH


def _step(
    key: tuple[int, EventKind],
    open_events: dict[tuple[int, EventKind], _OpenEvent | None],
    *,
    active: bool,
    first: bool,
    at_ns: int,
    service_start_ns: int,
    value_kg: int | None,
) -> list[ExpectedEvent]:
    opened = open_events.get(key)
    if first:
        if active:
            open_events[key] = _OpenEvent(
                start_ns=service_start_ns,
                start_value_kg=None,
                start_quality=StartQuality.UNKNOWN,
            )
        return []
    if opened is None and active:
        open_events[key] = _OpenEvent(
            start_ns=at_ns, start_value_kg=value_kg, start_quality=_start_quality(value_kg)
        )
        return []
    if opened is not None and not active:
        open_events[key] = None
        tank_id, kind = key
        return [
            ExpectedEvent(
                tank_id=tank_id,
                kind=kind,
                start_ns=opened.start_ns,
                end_ns=at_ns,
                start_value_kg=opened.start_value_kg,
                end_value_kg=value_kg,
                start_quality=opened.start_quality,
                end_quality=_end_quality(value_kg),
                collision=False,
                rule_violation=False,
            )
        ]
    return []
