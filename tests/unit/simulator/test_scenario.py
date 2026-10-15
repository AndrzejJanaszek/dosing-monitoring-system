from collections.abc import Callable

import pytest

from dms.acquisition.clock import NS_PER_S
from dms.simulator.layout import MeterDevice, PlantLayout, SiloLayout
from dms.simulator.scenario import (
    Dispense,
    Refill,
    Scenario,
    ScenarioError,
    SimulatedTankEvent,
)
from tests.unit.simulator.builders import (
    dispense,
    refill,
    scenario_with,
    tank,
    two_tank_layout,
)

TWO_SILOS = PlantLayout((SiloLayout(1, (tank(1, 4, 5),)), SiloLayout(2, (tank(2, 6, 7),))))


def test_valid_scenario_uses_default_start_mass_and_tail() -> None:
    scenario = scenario_with(dispense())

    assert scenario.start_mass_kg(1) == 20_000
    assert scenario.duration_ns == 43 * NS_PER_S


def test_explicit_duration_and_start_mass_are_used() -> None:
    scenario = scenario_with(dispense(), start_masses_kg={1: 5000}, duration_s=100)

    assert scenario.start_mass_kg(1) == 5000
    assert scenario.duration_ns == 100 * NS_PER_S


def test_scenario_without_events_needs_explicit_duration() -> None:
    assert scenario_with(duration_s=30).duration_ns == 30 * NS_PER_S


INVALID_SCENARIOS: dict[str, tuple[Callable[[], object], str]] = {
    "S1": (
        lambda: scenario_with(
            layout=PlantLayout((SiloLayout(1, (tank(1, 4, 5),)), SiloLayout(1, (tank(1, 6, 7),)))),
            duration_s=30,
        ),
        "duplicate",
    ),
    "S2": (
        lambda: scenario_with(layout=PlantLayout((SiloLayout(1, ()),)), duration_s=30),
        "tanks: 0 tanks",
    ),
    "S3": (lambda: scenario_with(dispense(tank_id=9)), "events[0].tank_id: unknown tank 9"),
    "S4-order": (lambda: scenario_with(dispense(40, 10)), "end must be after start"),
    "S4-mass": (lambda: scenario_with(dispense(mass_kg=0)), "end must be after start"),
    "S5-duration": (lambda: scenario_with(dispense(10, 11, 100)), "dispense duration 1"),
    "S5-rate": (lambda: scenario_with(dispense(10, 40, 100)), "dispense rate"),
    "S5-refill-duration": (lambda: scenario_with(refill(10, 40, 600)), "refill duration 30"),
    "S6": (lambda: scenario_with(dispense(2, 32)), "quiet period"),
    "S7-overlap": (lambda: scenario_with(dispense(10, 40), dispense(30, 60)), "events[1]"),
    "S7-touch": (lambda: scenario_with(dispense(10, 40), dispense(40, 70)), "events[1]"),
    "S7-gap": (lambda: scenario_with(dispense(10, 40), dispense(41, 71)), "events[1]"),
    "S8": (
        lambda: scenario_with(
            dispense(10, 40), dispense(20, 50, tank_id=2), layout=two_tank_layout()
        ),
        "same silo",
    ),
    "S9-start": (lambda: scenario_with(dispense(), start_masses_kg={1: -1}), "start mass -1"),
    "S9-time": (
        lambda: scenario_with(dispense(), start_masses_kg={1: 500}),
        "mass drops below zero",
    ),
    "S10-short": (lambda: scenario_with(dispense(), duration_s=30), "ends before the last event"),
    "S10-missing": (scenario_with, "required when there are no events"),
    "S11": (
        lambda: scenario_with(
            dispense(),
            layout=PlantLayout((SiloLayout(1, (tank(1, 4, 5),), MeterDevice(division_kg=1)),)),
            start_masses_kg={1: 123_456_789},
        ),
        "does not fit",
    ),
    "S12": (lambda: scenario_with(dispense(), start_masses_kg={7: 1}), "unknown silo 7"),
}


@pytest.mark.parametrize("rule", INVALID_SCENARIOS)
def test_invalid_scenario_is_rejected(rule: str) -> None:
    build, expected_fragment = INVALID_SCENARIOS[rule]

    with pytest.raises(ScenarioError) as raised:
        build()

    assert any(expected_fragment in error for error in raised.value.errors), raised.value.errors


def test_several_scenario_errors_are_reported_together() -> None:
    with pytest.raises(ScenarioError) as raised:
        scenario_with(dispense(tank_id=9), dispense(40, 10), dispense(2, 32))

    assert len(raised.value.errors) >= 3


def test_dispense_and_refill_overlap_on_one_tank_is_legal() -> None:
    scenario_with(refill(10, 310), dispense(100, 130))


def test_dispenses_on_different_silos_may_overlap() -> None:
    Scenario("test", TWO_SILOS, None, (dispense(10, 40), dispense(20, 50, tank_id=2)), None)


def test_event_kinds_and_signs() -> None:
    assert (Dispense.kind, Dispense.sign) == ("dispense", -1)
    assert (Refill.kind, Refill.sign) == ("refill", 1)
    assert isinstance(dispense(), SimulatedTankEvent)
