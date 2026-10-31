from collections.abc import Sequence
from dataclasses import dataclass

from dms.simulator.layout import (
    DEFAULT_ACTIVE_LEVEL,
    ErrorCode,
    FixedValue,
    Input,
    Missing,
    PlantLayout,
    SensorFault,
    SignalBoard,
    SiloLayout,
    TankWiring,
    TemperatureSensor,
)
from dms.simulator.scenario import Scenario
from dms.simulator.scenario_model import Dispense, Refill, SimulatedTankEvent

DISPENSE_DURATION_S = 30.0
DISPENSE_MASS_KG = 1_500
OTHER_TANK_DISPENSE_MASS_KG = 900
RUN_UP_DISPENSES = 3
RUN_UP_START_S = 10.0
RUN_UP_GAP_S = 10.0
RELATION_OFFSET_S = 250.0
REFILL_DURATION_S = 300.0
REFILL_MASS_KG = 6_000
OTHER_TANK_SUFFIX = "-other-tank"
IDLE_DURATION_S = 30.0
SHORT_DISPENSE_START_S = 3.0
SHORT_DISPENSE_END_S = 6.0
SHORT_DISPENSE_MASS_KG = 600
ACTIVE_HIGH_LEVEL = 1
TEMPERATURE_DURATION_S = 30.0
FIRST_SENSOR_ADDRESS = "28A8F126AB240B1C"
SECOND_SENSOR_ADDRESS = "28FF4A7C61160398"
OUTSIDE_SENSOR_ADDRESS = "28B3C41D5E6F7A80"
RISING_RATE_C_PER_MIN = 6.0
SLOW_RATE_C_PER_MIN = 3.0


def _tank(
    tank_id: int, dispense_pin: int, refill_pin: int, active_level: int = DEFAULT_ACTIVE_LEVEL
) -> TankWiring:
    return TankWiring(
        id=tank_id,
        dispense=Input(pin=dispense_pin, active_level=active_level),
        refill=Input(pin=refill_pin, active_level=active_level),
    )


ONE_TANK = PlantLayout((SiloLayout(id=1, tanks=(_tank(1, 4, 5),)),))
TWO_TANKS = PlantLayout((SiloLayout(id=1, tanks=(_tank(1, 4, 5), _tank(2, 6, 7))),))
TWO_SILOS = PlantLayout(
    (SiloLayout(id=1, tanks=(_tank(1, 4, 5),)), SiloLayout(id=2, tanks=(_tank(2, 6, 7),))),
)
ONE_TANK_ACTIVE_HIGH = PlantLayout(
    (SiloLayout(id=1, tanks=(_tank(1, 4, 5, ACTIVE_HIGH_LEVEL),)),),
)
ONE_TANK_WITH_SENSORS = PlantLayout(
    ONE_TANK.silos,
    SignalBoard(
        sensors=(
            TemperatureSensor(id=1, address="28A8F126AB240B1C", start_c=21.5, silo_id=1, leg=1),
            TemperatureSensor(id=2, address="28FF4A7C61160398", start_c=22.25, silo_id=1, leg=2),
        )
    ),
)


@dataclass(frozen=True, slots=True)
class Relation:
    name: str
    refill_start_s: float
    dispense_starts_s: tuple[float, ...]


def _dispense(tank_id: int, start_s: float, mass_kg: int = DISPENSE_MASS_KG) -> Dispense:
    return Dispense(
        tank_id=tank_id,
        start_s=start_s,
        end_s=start_s + DISPENSE_DURATION_S,
        mass_kg=mass_kg,
    )


def _run_up(*masses_by_tank: tuple[int, int]) -> list[Dispense]:
    run_up: list[Dispense] = []
    start_s = RUN_UP_START_S
    for tank_id, mass_kg in masses_by_tank:
        for _ in range(RUN_UP_DISPENSES):
            run_up.append(_dispense(tank_id, start_s, mass_kg))
            start_s += DISPENSE_DURATION_S + RUN_UP_GAP_S
    return run_up


def _refill(tank_id: int, start_s: float) -> Refill:
    return Refill(
        tank_id=tank_id, start_s=start_s, end_s=start_s + REFILL_DURATION_S, mass_kg=REFILL_MASS_KG
    )


def _scenario(
    name: str, layout: PlantLayout, *events: SimulatedTankEvent, duration_s: float | None = None
) -> Scenario:
    return Scenario(
        name=name,
        layout=layout,
        start_masses_kg=None,
        events=tuple(events),
        duration_s=duration_s,
    )


def _rule_violation(name: str, *events: SimulatedTankEvent) -> Scenario:
    return Scenario(
        name=name,
        layout=TWO_TANKS,
        start_masses_kg=None,
        events=tuple(events),
        allow_rule_violations=True,
    )


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
    masses_by_tank = [(dispense_tank, DISPENSE_MASS_KG)]
    if refill_tank != dispense_tank:
        masses_by_tank.append((refill_tank, OTHER_TANK_DISPENSE_MASS_KG))
    run_up = _run_up(*masses_by_tank)
    return [
        _scenario(
            f"{relation.name}{suffix}",
            layout,
            *run_up,
            _refill(refill_tank, RELATION_OFFSET_S + relation.refill_start_s),
            *(
                _dispense(dispense_tank, RELATION_OFFSET_S + start_s)
                for start_s in relation.dispense_starts_s
            ),
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
            Dispense(
                tank_id=1,
                start_s=SHORT_DISPENSE_START_S,
                end_s=SHORT_DISPENSE_END_S,
                mass_kg=SHORT_DISPENSE_MASS_KG,
            ),
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
        _scenario(
            "refill-with-dispenses-both-tanks-after-run-up",
            TWO_TANKS,
            *_run_up((1, DISPENSE_MASS_KG), (2, OTHER_TANK_DISPENSE_MASS_KG)),
            _refill(1, RELATION_OFFSET_S + 10),
            _dispense(1, RELATION_OFFSET_S + 50),
            _dispense(2, RELATION_OFFSET_S + 120, OTHER_TANK_DISPENSE_MASS_KG),
            _dispense(1, RELATION_OFFSET_S + 190),
        ),
    ]


def _rule_violations() -> list[Scenario]:
    return [
        _rule_violation("dispense-both-tanks-concurrent", _dispense(1, 10), _dispense(2, 20)),
        _rule_violation(
            "refill-with-concurrent-dispenses-both-tanks",
            _refill(1, 10),
            _dispense(1, 50),
            _dispense(2, 60),
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


def _sensor_layout(*sensors: TemperatureSensor) -> PlantLayout:
    return PlantLayout(ONE_TANK.silos, SignalBoard(sensors=sensors))


def _fault(start_s: float, end_s: float, kind: ErrorCode | FixedValue | Missing) -> SensorFault:
    return SensorFault(start_s=start_s, end_s=end_s, kind=kind)


def _temperatures() -> list[Scenario]:
    rising = _sensor_layout(
        TemperatureSensor(
            id=1,
            address=FIRST_SENSOR_ADDRESS,
            start_c=20.0,
            rate_c_per_min=RISING_RATE_C_PER_MIN,
            silo_id=1,
            leg=1,
        ),
        TemperatureSensor(
            id=2,
            address=SECOND_SENSOR_ADDRESS,
            start_c=20.5,
            rate_c_per_min=SLOW_RATE_C_PER_MIN,
            silo_id=1,
            leg=2,
        ),
    )
    ambient = _sensor_layout(
        TemperatureSensor(id=1, address=FIRST_SENSOR_ADDRESS, start_c=21.5, silo_id=1, leg=1),
        TemperatureSensor(
            id=2,
            address=SECOND_SENSOR_ADDRESS,
            start_c=12.0,
            rate_c_per_min=RISING_RATE_C_PER_MIN / 5,
            name="Otoczenie",
        ),
    )
    errors = _sensor_layout(
        TemperatureSensor(
            id=1,
            address=FIRST_SENSOR_ADDRESS,
            start_c=20.0,
            rate_c_per_min=RISING_RATE_C_PER_MIN,
            silo_id=1,
            leg=1,
            faults=(
                _fault(6, 8, ErrorCode("read_failed")),
                _fault(12, 14, ErrorCode("power_reset")),
                _fault(18, 20, ErrorCode("insufficient_power")),
                _fault(24, 26, ErrorCode("crc_error")),
            ),
        )
    )
    out_of_range = _sensor_layout(
        TemperatureSensor(
            id=1,
            address=FIRST_SENSOR_ADDRESS,
            start_c=20.0,
            rate_c_per_min=RISING_RATE_C_PER_MIN,
            silo_id=1,
            leg=1,
            faults=(
                _fault(6, 8, FixedValue(-127.0)),
                _fault(12, 14, FixedValue(85.0)),
                _fault(18, 20, FixedValue(150.25)),
            ),
        )
    )
    missing = _sensor_layout(
        TemperatureSensor(
            id=1,
            address=FIRST_SENSOR_ADDRESS,
            start_c=20.0,
            rate_c_per_min=RISING_RATE_C_PER_MIN,
            silo_id=1,
            leg=1,
            faults=(_fault(8, 18, Missing()),),
        )
    )
    unknown = _sensor_layout(
        TemperatureSensor(
            id=1,
            address=FIRST_SENSOR_ADDRESS,
            start_c=20.0,
            rate_c_per_min=RISING_RATE_C_PER_MIN,
            silo_id=1,
            leg=1,
        ),
        TemperatureSensor(
            id=2,
            address=OUTSIDE_SENSOR_ADDRESS,
            start_c=18.0,
            rate_c_per_min=SLOW_RATE_C_PER_MIN,
            configured=False,
            faults=(_fault(10, 20, Missing()),),
        ),
    )
    return [
        _scenario("temperatures-rising", rising, duration_s=TEMPERATURE_DURATION_S),
        _scenario("temperatures-ambient-sensor", ambient, duration_s=TEMPERATURE_DURATION_S),
        _scenario("temperatures-sensor-errors", errors, duration_s=TEMPERATURE_DURATION_S),
        _scenario("temperatures-out-of-range", out_of_range, duration_s=TEMPERATURE_DURATION_S),
        _scenario(
            "temperatures-sensor-missing-and-back", missing, duration_s=TEMPERATURE_DURATION_S
        ),
        _scenario("temperatures-unknown-sensor", unknown, duration_s=TEMPERATURE_DURATION_S),
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
        *_rule_violations(),
        *_two_silos(),
        *_polarity_and_sensors(),
        *_temperatures(),
    ]
)
