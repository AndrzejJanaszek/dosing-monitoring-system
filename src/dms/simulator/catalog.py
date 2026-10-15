from collections.abc import Sequence
from dataclasses import dataclass

from dms.simulator.layout import (
    DEFAULT_ACTIVE_LEVEL,
    Input,
    PlantLayout,
    SignalBoard,
    SiloLayout,
    TankWiring,
    TemperatureSensor,
)
from dms.simulator.scenario import Dispense, Refill, Scenario, SimulatedTankEvent

DISPENSE_DURATION_S = 30.0
DISPENSE_MASS_KG = 1_500
REFILL_DURATION_S = 300.0
REFILL_MASS_KG = 6_000
OTHER_TANK_SUFFIX = "-other-tank"
IDLE_DURATION_S = 30.0
SHORT_DISPENSE_START_S = 3.0
SHORT_DISPENSE_END_S = 6.0
SHORT_DISPENSE_MASS_KG = 600
ACTIVE_HIGH_LEVEL = 1


def _tank(
    tank_id: int, dispense_pin: int, refill_pin: int, active_level: int = DEFAULT_ACTIVE_LEVEL
) -> TankWiring:
    return TankWiring(tank_id, Input(dispense_pin, active_level), Input(refill_pin, active_level))


ONE_TANK = PlantLayout((SiloLayout(1, (_tank(1, 4, 5),)),))
TWO_TANKS = PlantLayout((SiloLayout(1, (_tank(1, 4, 5), _tank(2, 6, 7))),))
TWO_SILOS = PlantLayout(
    (SiloLayout(1, (_tank(1, 4, 5),)), SiloLayout(2, (_tank(2, 6, 7),))),
)
ONE_TANK_ACTIVE_HIGH = PlantLayout(
    (SiloLayout(1, (_tank(1, 4, 5, ACTIVE_HIGH_LEVEL),)),),
)
ONE_TANK_WITH_SENSORS = PlantLayout(
    ONE_TANK.silos,
    SignalBoard(
        sensors=(
            TemperatureSensor("28A8F126AB240B1C", 21.5),
            TemperatureSensor("28FF4A7C61160398", 22.25),
        )
    ),
)


@dataclass(frozen=True, slots=True)
class Relation:
    name: str
    refill_start_s: float
    dispense_starts_s: tuple[float, ...]


def _dispense(tank_id: int, start_s: float) -> Dispense:
    return Dispense(tank_id, start_s, start_s + DISPENSE_DURATION_S, DISPENSE_MASS_KG)


def _refill(tank_id: int, start_s: float) -> Refill:
    return Refill(tank_id, start_s, start_s + REFILL_DURATION_S, REFILL_MASS_KG)


def _scenario(
    name: str, layout: PlantLayout, *events: SimulatedTankEvent, duration_s: float | None = None
) -> Scenario:
    return Scenario(name, layout, None, tuple(events), duration_s)


RELATIONS = (
    Relation("dispense-before-refill", 100, (10,)),
    Relation("dispense-after-refill", 10, (340,)),
    Relation("dispense-meets-refill", 40, (10,)),
    Relation("refill-meets-dispense", 10, (310,)),
    Relation("dispense-front-refill", 100, (90,)),
    Relation("dispense-inner-refill", 10, (100,)),
    Relation("dispense-back-refill", 10, (295,)),
    Relation("dispense-starts-with-refill", 10, (10,)),
    Relation("dispense-ends-with-refill", 10, (280,)),
    Relation("dispense-multi-inner-refill", 10, (50, 120, 190)),
    Relation("dispense-front-multi-inner-back-refill", 100, (90, 180, 270, 390)),
)


def dispense_refill_relations(
    layout: PlantLayout, dispense_tank: int, refill_tank: int, suffix: str
) -> list[Scenario]:
    return [
        _scenario(
            f"{relation.name}{suffix}",
            layout,
            _refill(refill_tank, relation.refill_start_s),
            *(_dispense(dispense_tank, start_s) for start_s in relation.dispense_starts_s),
        )
        for relation in RELATIONS
    ]


def _pure_events() -> list[Scenario]:
    return [
        _scenario("idle", ONE_TANK, duration_s=IDLE_DURATION_S),
        _scenario("dispense-single", ONE_TANK, _dispense(1, 10)),
        _scenario(
            "dispense-short",
            ONE_TANK,
            Dispense(1, SHORT_DISPENSE_START_S, SHORT_DISPENSE_END_S, SHORT_DISPENSE_MASS_KG),
        ),
        _scenario("refill-single", ONE_TANK, _refill(1, 10)),
        _scenario(
            "dispense-series", ONE_TANK, _dispense(1, 10), _dispense(1, 50), _dispense(1, 90)
        ),
    ]


def _two_tank_series() -> list[Scenario]:
    return [
        _scenario(
            "dispense-both-tanks-series",
            TWO_TANKS,
            _dispense(1, 10),
            _dispense(2, 50),
            _dispense(1, 90),
        ),
        _scenario("refill-both-tanks-series", TWO_TANKS, _refill(1, 10), _refill(2, 320)),
        _scenario(
            "refill-with-dispenses-both-tanks",
            TWO_TANKS,
            _refill(1, 10),
            _dispense(1, 50),
            _dispense(2, 120),
            _dispense(1, 190),
        ),
    ]


def _two_silos() -> list[Scenario]:
    return [
        _scenario("two-silos-concurrent-dispenses", TWO_SILOS, _dispense(1, 10), _dispense(2, 20)),
        _scenario("two-silos-refill-and-dispense", TWO_SILOS, _refill(1, 10), _dispense(2, 100)),
    ]


def _polarity_and_sensors() -> list[Scenario]:
    return [
        _scenario("dispense-single-active-high", ONE_TANK_ACTIVE_HIGH, _dispense(1, 10)),
        _scenario("dispense-single-with-sensors", ONE_TANK_WITH_SENSORS, _dispense(1, 10)),
    ]


def build_catalog(scenarios: Sequence[Scenario]) -> dict[str, Scenario]:
    catalog: dict[str, Scenario] = {}
    for scenario in scenarios:
        if scenario.name in catalog:
            raise ValueError(f"duplicate scenario name '{scenario.name}'")
        catalog[scenario.name] = scenario
    return catalog


SCENARIOS = build_catalog(
    [
        *_pure_events(),
        *dispense_refill_relations(ONE_TANK, 1, 1, ""),
        *dispense_refill_relations(TWO_TANKS, 1, 2, OTHER_TANK_SUFFIX),
        *_two_tank_series(),
        *_two_silos(),
        *_polarity_and_sensors(),
    ]
)
