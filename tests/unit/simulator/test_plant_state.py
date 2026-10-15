import pytest

from dms.acquisition.clock import NS_PER_S
from dms.simulator.layout import MeterDevice, PlantLayout, SiloLayout
from dms.simulator.plant_state import indication_kg, pin_levels, signal_active, silo_mass_kg
from dms.simulator.scenario import Refill
from tests.unit.simulator.builders import dispense, scenario_with, tank, two_tank_layout


def seconds(value: float) -> int:
    return round(value * NS_PER_S)


def test_mass_before_during_and_after_dispense() -> None:
    scenario = scenario_with(dispense(10, 40, 1500))

    assert silo_mass_kg(scenario, 1, seconds(5)) == 20_000
    assert silo_mass_kg(scenario, 1, seconds(25)) == 19_250
    assert silo_mass_kg(scenario, 1, seconds(60)) == 18_500


def test_overlapping_dispense_and_refill_add_up() -> None:
    scenario = scenario_with(Refill(1, 10, 310, 6000), dispense(100, 130, 1500))

    assert silo_mass_kg(scenario, 1, seconds(115)) == 20_000 + 2_100 - 750
    assert silo_mass_kg(scenario, 1, seconds(400)) == 20_000 + 6_000 - 1_500


def test_events_of_other_silo_do_not_change_mass() -> None:
    layout = PlantLayout((SiloLayout(1, (tank(1, 4, 5),)), SiloLayout(2, (tank(2, 6, 7),))))
    scenario = scenario_with(dispense(10, 40, 1500, tank_id=2), layout=layout)

    assert silo_mass_kg(scenario, 1, seconds(60)) == 20_000
    assert silo_mass_kg(scenario, 2, seconds(60)) == 18_500


@pytest.mark.parametrize(
    ("mass_kg", "expected"), [(19_989.0, 19_980), (19_991.0, 20_000), (20_000.0, 20_000)]
)
def test_indication_rounds_to_division(mass_kg: float, expected: int) -> None:
    assert indication_kg(mass_kg, MeterDevice(division_kg=20)) == expected


def test_signal_interval_is_half_open() -> None:
    scenario = scenario_with(dispense(10, 40))

    assert not signal_active(scenario, 1, "dispense", seconds(10) - 1)
    assert signal_active(scenario, 1, "dispense", seconds(10))
    assert signal_active(scenario, 1, "dispense", seconds(40) - 1)
    assert not signal_active(scenario, 1, "dispense", seconds(40))
    assert not signal_active(scenario, 1, "refill", seconds(20))


def test_pin_levels_for_active_low_wiring() -> None:
    scenario = scenario_with(dispense(10, 40), layout=two_tank_layout())

    assert pin_levels(scenario, seconds(5)) == tuple((pin, 1) for pin in range(4, 10))
    assert pin_levels(scenario, seconds(20)) == (
        (4, 0),
        (5, 1),
        (6, 1),
        (7, 1),
        (8, 1),
        (9, 1),
    )


def test_pin_levels_for_active_high_wiring() -> None:
    layout = PlantLayout((SiloLayout(1, (tank(1, 4, 5, active_level=1),)),))
    scenario = scenario_with(dispense(10, 40), layout=layout)

    assert pin_levels(scenario, seconds(5))[:2] == ((4, 0), (5, 0))
    assert pin_levels(scenario, seconds(20))[:2] == ((4, 1), (5, 0))
    assert pin_levels(scenario, seconds(5))[2:] == tuple((pin, 1) for pin in range(6, 10))
