import itertools
from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Literal

from dms.acquisition.clock import NS_PER_S
from dms.simulator.encoders import METER_ENCODERS
from dms.simulator.errors import ScenarioError
from dms.simulator.layout import PlantLayout, SiloLayout
from dms.simulator.plant_state import indication_kg, silo_mass_kg
from dms.simulator.profiles import LINEAR, Profile

__all__ = [
    "Dispense",
    "EventKind",
    "Refill",
    "Scenario",
    "ScenarioError",
    "SimulatedTankEvent",
]

type EventKind = Literal["dispense", "refill"]

DEFAULT_START_MASS_KG = 20_000
QUIET_PERIOD_S = 3.0
TAIL_S = 3.0
MIN_GAP_S = 2.0
DISPENSE_DURATION_RANGE_S = (2.0, 45.0)
DISPENSE_RATE_RANGE_KG_PER_S = (5.0, 1_000.0)
REFILL_DURATION_RANGE_S = (60.0, 1_200.0)
REFILL_RATE_RANGE_KG_PER_S = (1.0, 200.0)


@dataclass(frozen=True, slots=True)
class SimulatedTankEvent:
    tank_id: int
    start_s: float
    end_s: float
    mass_kg: int
    profile: Profile = LINEAR
    kind: ClassVar[EventKind]
    sign: ClassVar[int]
    duration_range_s: ClassVar[tuple[float, float]]
    rate_range_kg_per_s: ClassVar[tuple[float, float]]

    @property
    def start_ns(self) -> int:
        return round(self.start_s * NS_PER_S)

    @property
    def end_ns(self) -> int:
        return round(self.end_s * NS_PER_S)

    def progress(self, t_ns: int) -> float:
        return min(max((t_ns - self.start_ns) / (self.end_ns - self.start_ns), 0.0), 1.0)


@dataclass(frozen=True, slots=True)
class Dispense(SimulatedTankEvent):
    kind: ClassVar[EventKind] = "dispense"
    sign: ClassVar[int] = -1
    duration_range_s: ClassVar[tuple[float, float]] = DISPENSE_DURATION_RANGE_S
    rate_range_kg_per_s: ClassVar[tuple[float, float]] = DISPENSE_RATE_RANGE_KG_PER_S


@dataclass(frozen=True, slots=True)
class Refill(SimulatedTankEvent):
    kind: ClassVar[EventKind] = "refill"
    sign: ClassVar[int] = 1
    duration_range_s: ClassVar[tuple[float, float]] = REFILL_DURATION_RANGE_S
    rate_range_kg_per_s: ClassVar[tuple[float, float]] = REFILL_RATE_RANGE_KG_PER_S


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    layout: PlantLayout
    start_masses_kg: Mapping[int, int] | None
    events: tuple[SimulatedTankEvent, ...]
    duration_s: float | None = None

    def __post_init__(self) -> None:
        errors = [
            *_start_mass_errors(self),
            *_event_errors(self),
            *_duration_errors(self),
        ]
        if not errors:
            errors = _mass_errors(self)
        if errors:
            raise ScenarioError(errors)

    @property
    def duration_ns(self) -> int:
        if self.duration_s is not None:
            return round(self.duration_s * NS_PER_S)
        return max(event.end_ns for event in self.events) + round(TAIL_S * NS_PER_S)

    def start_mass_kg(self, silo_id: int) -> int:
        masses = self.start_masses_kg or {}
        return masses.get(silo_id, DEFAULT_START_MASS_KG)


def _start_mass_errors(scenario: Scenario) -> list[str]:
    errors: list[str] = []
    silo_ids = {silo.id for silo in scenario.layout.silos}
    for silo_id, mass_kg in (scenario.start_masses_kg or {}).items():
        if silo_id not in silo_ids:
            errors.append(f"start_masses_kg[{silo_id}]: unknown silo {silo_id}")
        if mass_kg < 0:
            errors.append(f"start_masses_kg[{silo_id}]: start mass {mass_kg} kg is negative")
    return errors


def _event_errors(scenario: Scenario) -> list[str]:
    tank_ids = {tank.id for silo in scenario.layout.silos for tank in silo.tanks}
    errors: list[str] = []
    valid: list[tuple[int, SimulatedTankEvent]] = []
    for index, event in enumerate(scenario.events):
        event_errors = _single_event_errors(index, event, tank_ids)
        errors.extend(event_errors)
        if not event_errors:
            valid.append((index, event))
    return [*errors, *_gap_errors(scenario.layout, valid)]


def _single_event_errors(index: int, event: SimulatedTankEvent, tank_ids: set[int]) -> list[str]:
    path = f"events[{index}]"
    if event.tank_id not in tank_ids:
        return [f"{path}.tank_id: unknown tank {event.tank_id}"]
    if event.end_s <= event.start_s or event.mass_kg <= 0:
        return [f"{path}: end must be after start and mass positive"]

    errors: list[str] = []
    duration_s = event.end_s - event.start_s
    rate_kg_per_s = event.mass_kg / duration_s
    for name, value, (low, high) in (
        ("duration", duration_s, event.duration_range_s),
        ("rate", rate_kg_per_s, event.rate_range_kg_per_s),
    ):
        if not low <= value <= high:
            errors.append(f"{path}: {event.kind} {name} {value:g} is outside {low:g}..{high:g}")

    if event.start_s < QUIET_PERIOD_S:
        errors.append(
            f"{path}.start_s: {event.start_s:g} s is inside the {QUIET_PERIOD_S:g} s quiet period"
        )
    return errors


def _gap_errors(layout: PlantLayout, events: list[tuple[int, SimulatedTankEvent]]) -> list[str]:
    errors: list[str] = []
    ordered = sorted(events, key=lambda item: item[1].start_s)
    for (_, earlier), (later_index, later) in itertools.combinations(ordered, 2):
        if earlier.kind != later.kind:
            continue
        if later.start_s >= earlier.end_s + MIN_GAP_S:
            continue

        same_tank = earlier.tank_id == later.tank_id
        same_silo = layout.silo_of(earlier.tank_id).id == layout.silo_of(later.tank_id).id
        if same_tank:
            errors.append(
                f"events[{later_index}]: {later.kind} closer than {MIN_GAP_S:g} s after another on tank {later.tank_id}"
            )
        elif same_silo:
            errors.append(
                f"events[{later_index}]: {later.kind} closer than {MIN_GAP_S:g} s after another on the same silo"
            )
    return errors


def _duration_errors(scenario: Scenario) -> list[str]:
    if not scenario.events:
        if scenario.duration_s is None:
            return ["duration_s: required when there are no events"]
        return []
    last_end_s = max(event.end_s for event in scenario.events)
    if scenario.duration_s is not None and scenario.duration_s < last_end_s:
        return [
            f"duration_s: {scenario.duration_s:g} s ends before the last event at {last_end_s:g} s"
        ]
    return []


def _mass_errors(scenario: Scenario) -> list[str]:
    errors: list[str] = []
    for silo in scenario.layout.silos:
        errors.extend(_silo_mass_errors(scenario, silo))
    return errors


def _silo_mass_errors(scenario: Scenario, silo: SiloLayout) -> list[str]:
    period_ns = round(NS_PER_S / silo.meter.rate_hz)
    sample_times = range(0, scenario.duration_ns + 1, period_ns)
    boundary_times = [t_ns for event in scenario.events for t_ns in (event.start_ns, event.end_ns)]
    masses = [silo_mass_kg(scenario, silo.id, t_ns) for t_ns in (*sample_times, *boundary_times)]

    errors: list[str] = []
    if min(masses) < 0:
        errors.append(f"silos[{silo.id}]: mass drops below zero ({min(masses):g} kg)")

    max_indication = indication_kg(max(masses), silo.meter)
    try:
        METER_ENCODERS[silo.meter.format](max_indication)
    except ValueError as error:
        errors.append(f"silos[{silo.id}]: {error}")
    return errors
