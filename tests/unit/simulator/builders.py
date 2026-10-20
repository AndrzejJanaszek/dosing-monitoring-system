from dms.simulator.layout import Input, PlantLayout, SiloLayout, TankWiring
from dms.simulator.scenario import Dispense, Refill, Scenario, SimulatedTankEvent


def tank(tank_id: int, dispense_pin: int, refill_pin: int, active_level: int = 0) -> TankWiring:
    return TankWiring(tank_id, Input(dispense_pin, active_level), Input(refill_pin, active_level))


def one_tank_layout() -> PlantLayout:
    return PlantLayout((SiloLayout(1, (tank(1, 4, 5),)),))


def two_tank_layout() -> PlantLayout:
    return PlantLayout((SiloLayout(1, (tank(1, 4, 5), tank(2, 6, 7))),))


def refill(
    start_s: float = 10.0, end_s: float = 310.0, mass_kg: int = 6000, tank_id: int = 1
) -> Refill:
    return Refill(tank_id, start_s, end_s, mass_kg)


def scenario_with(
    *events: SimulatedTankEvent,
    layout: PlantLayout | None = None,
    start_masses_kg: dict[int, int] | None = None,
    duration_s: float | None = None,
) -> Scenario:
    return Scenario(
        "test", layout or one_tank_layout(), start_masses_kg, tuple(events), duration_s
    )


def dispense(
    start_s: float = 10.0, end_s: float = 40.0, mass_kg: int = 1500, tank_id: int = 1
) -> Dispense:
    return Dispense(tank_id, start_s, end_s, mass_kg)
