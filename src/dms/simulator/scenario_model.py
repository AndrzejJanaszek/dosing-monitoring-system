from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

from dms.domain.events import EventKind
from dms.simulator.layout import PlantLayout
from dms.simulator.profiles import LINEAR, Profile
from dms.units import NS_PER_S

DEFAULT_START_MASS_KG = 20_000
TAIL_S = 3.0
DISPENSE_DURATION_RANGE_S = (2.0, 45.0)
DISPENSE_RATE_RANGE_KG_PER_S = (5.0, 1_000.0)
REFILL_DURATION_RANGE_S = (60.0, 1_200.0)
REFILL_RATE_RANGE_KG_PER_S = (1.0, 200.0)


@dataclass(frozen=True, slots=True, kw_only=True)
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


@dataclass(frozen=True, slots=True, kw_only=True)
class Dispense(SimulatedTankEvent):
    kind: ClassVar[EventKind] = EventKind.DISPENSE
    sign: ClassVar[int] = -1
    duration_range_s: ClassVar[tuple[float, float]] = DISPENSE_DURATION_RANGE_S
    rate_range_kg_per_s: ClassVar[tuple[float, float]] = DISPENSE_RATE_RANGE_KG_PER_S


@dataclass(frozen=True, slots=True, kw_only=True)
class Refill(SimulatedTankEvent):
    kind: ClassVar[EventKind] = EventKind.REFILL
    sign: ClassVar[int] = 1
    duration_range_s: ClassVar[tuple[float, float]] = REFILL_DURATION_RANGE_S
    rate_range_kg_per_s: ClassVar[tuple[float, float]] = REFILL_RATE_RANGE_KG_PER_S


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioData:
    name: str
    layout: PlantLayout
    start_masses_kg: Mapping[int, int] | None
    events: tuple[SimulatedTankEvent, ...]
    duration_s: float | None = None
    allow_rule_violations: bool = False

    @property
    def duration_ns(self) -> int:
        if self.duration_s is not None:
            return round(self.duration_s * NS_PER_S)
        return max(event.end_ns for event in self.events) + round(TAIL_S * NS_PER_S)

    def start_mass_kg(self, silo_id: int) -> int:
        masses = self.start_masses_kg or {}
        return masses.get(silo_id, DEFAULT_START_MASS_KG)
