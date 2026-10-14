from collections.abc import Sequence
from dataclasses import dataclass

from dms.simulator.layout import Input
from dms.simulator.scenario import EventKind, Scenario
from dms.simulator.timeline import MeterSample, PinsSample, Sample

FRESH = "fresh"
STALE_READING = "stale_reading"
UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ExpectedEvent:
    tank_id: int
    kind: EventKind
    start_ns: int
    end_ns: int
    start_value_kg: int | None
    end_value_kg: int | None
    start_quality: str
    end_quality: str


@dataclass(frozen=True, slots=True)
class _OpenEvent:
    start_ns: int
    start_value_kg: int | None
    start_quality: str


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
    return expected


def _wirings(dispense: Input, refill: Input) -> tuple[tuple[EventKind, Input], ...]:
    return (("dispense", dispense), ("refill", refill))


def _fresh_value_kg(
    meter_sample: MeterSample | None, at_ns: int, max_reading_age_ns: int
) -> int | None:
    if meter_sample is None or at_ns - meter_sample.at_ns > max_reading_age_ns:
        return None
    return meter_sample.value_kg


def _quality(value_kg: int | None) -> str:
    return STALE_READING if value_kg is None else FRESH


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
            open_events[key] = _OpenEvent(service_start_ns, None, UNKNOWN)
        return []
    if opened is None and active:
        open_events[key] = _OpenEvent(at_ns, value_kg, _quality(value_kg))
        return []
    if opened is not None and not active:
        open_events[key] = None
        tank_id, kind = key
        return [
            ExpectedEvent(
                tank_id,
                kind,
                opened.start_ns,
                at_ns,
                opened.start_value_kg,
                value_kg,
                opened.start_quality,
                _quality(value_kg),
            )
        ]
    return []
