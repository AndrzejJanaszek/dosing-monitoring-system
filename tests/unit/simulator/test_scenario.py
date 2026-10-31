from collections.abc import Callable

import pytest

from dms.simulator.errors import ScenarioError
from dms.simulator.layout import (
    MeterDevice,
    Missing,
    PlantLayout,
    SensorFault,
    SignalBoard,
    SiloLayout,
    TemperatureSensor,
)
from dms.simulator.scenario import Scenario
from dms.simulator.scenario_model import Dispense, Refill, SimulatedTankEvent
from dms.units import NS_PER_S
from tests.unit.simulator.builders import (
    dispense,
    refill,
    scenario_with,
    tank,
    two_tank_layout,
)

TWO_SILOS = PlantLayout(
    (SiloLayout(id=1, tanks=(tank(1, 4, 5),)), SiloLayout(id=2, tanks=(tank(2, 6, 7),)))
)


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


def idle_with_fault(end_s: float, duration_s: float | None = 30) -> Scenario:
    sensor = TemperatureSensor(
        id=1,
        address="28A8F126AB240B1C",
        start_c=20.0,
        faults=(SensorFault(start_s=1.0, end_s=end_s, kind=Missing()),),
    )
    layout = PlantLayout(two_tank_layout().silos, SignalBoard(sensors=(sensor,)))
    return scenario_with(layout=layout, duration_s=duration_s)


def test_sensor_fault_may_last_until_the_end_of_the_scenario() -> None:
    assert idle_with_fault(30.0).duration_ns == 30 * NS_PER_S


INVALID_SCENARIOS: dict[str, tuple[Callable[[], object], str]] = {
    "sensor-fault-without-duration": (
        lambda: idle_with_fault(5.0, duration_s=None),
        "duration_s: required when there are no events",
    ),
    "duplicate-silo-id": (
        lambda: scenario_with(
            layout=PlantLayout(
                (
                    SiloLayout(id=1, tanks=(tank(1, 4, 5),)),
                    SiloLayout(id=1, tanks=(tank(1, 6, 7),)),
                )
            ),
            duration_s=30,
        ),
        "duplicate",
    ),
    "silo-without-tanks": (
        lambda: scenario_with(layout=PlantLayout((SiloLayout(id=1, tanks=()),)), duration_s=30),
        "tanks: 0 tanks",
    ),
    "event-on-unknown-tank": (
        lambda: scenario_with(dispense(tank_id=9)),
        "events[0].tank_id: unknown tank 9",
    ),
    "end-before-start": (lambda: scenario_with(dispense(40, 10)), "end must be after start"),
    "zero-mass": (lambda: scenario_with(dispense(mass_kg=0)), "end must be after start"),
    "dispense-too-short": (lambda: scenario_with(dispense(10, 11, 100)), "dispense duration 1"),
    "dispense-rate-too-high": (lambda: scenario_with(dispense(10, 40, 100)), "dispense rate"),
    "refill-too-long": (lambda: scenario_with(refill(10, 40, 600)), "refill duration 30"),
    "event-too-soon-after-start": (lambda: scenario_with(dispense(2, 32)), "quiet period"),
    "events-overlap-on-tank": (
        lambda: scenario_with(dispense(10, 40), dispense(30, 60)),
        "events[1]",
    ),
    "events-touch-on-tank": (
        lambda: scenario_with(dispense(10, 40), dispense(40, 70)),
        "events[1]",
    ),
    "events-too-close-on-tank": (
        lambda: scenario_with(dispense(10, 40), dispense(41, 71)),
        "events[1]",
    ),
    "events-overlap-on-silo": (
        lambda: scenario_with(
            dispense(10, 40), dispense(20, 50, tank_id=2), layout=two_tank_layout()
        ),
        "same silo",
    ),
    "negative-start-mass": (
        lambda: scenario_with(dispense(), start_masses_kg={1: -1}),
        "start mass -1",
    ),
    "mass-drops-below-zero": (
        lambda: scenario_with(dispense(), start_masses_kg={1: 500}),
        "mass drops below zero",
    ),
    "duration-before-last-event": (
        lambda: scenario_with(dispense(), duration_s=30),
        "ends before the last event",
    ),
    "sensor-fault-after-the-end": (
        lambda: idle_with_fault(30.5),
        "board.sensors[0].faults[0]: ends after the scenario",
    ),
    "duration-missing": (scenario_with, "required when there are no events"),
    "mass-does-not-fit-division": (
        lambda: scenario_with(
            dispense(),
            layout=PlantLayout(
                (SiloLayout(id=1, tanks=(tank(1, 4, 5),), meter=MeterDevice(division_kg=1)),)
            ),
            start_masses_kg={1: 123_456_789},
        ),
        "does not fit",
    ),
    "start-mass-for-unknown-silo": (
        lambda: scenario_with(dispense(), start_masses_kg={7: 1}),
        "unknown silo 7",
    ),
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
    Scenario(
        name="test",
        layout=TWO_SILOS,
        start_masses_kg=None,
        events=(dispense(10, 40), dispense(20, 50, tank_id=2)),
        duration_s=None,
    )


def test_same_type_on_both_tanks_of_a_silo_is_legal_when_rule_violations_are_allowed() -> None:
    Scenario(
        name="test",
        layout=two_tank_layout(),
        start_masses_kg=None,
        events=(dispense(10, 40), dispense(20, 50, tank_id=2)),
        allow_rule_violations=True,
    )


def test_allowed_rule_violations_still_refuse_overlapping_events_on_one_tank() -> None:
    with pytest.raises(ScenarioError) as raised:
        Scenario(
            name="test",
            layout=two_tank_layout(),
            start_masses_kg=None,
            events=(dispense(10, 40), dispense(30, 60)),
            allow_rule_violations=True,
        )

    assert raised.value.errors == ["events[1]: dispense closer than 2 s after another on tank 1"]


def test_event_kinds_and_signs() -> None:
    assert (Dispense.kind, Dispense.sign) == ("dispense", -1)
    assert (Refill.kind, Refill.sign) == ("refill", 1)
    assert isinstance(dispense(), SimulatedTankEvent)
