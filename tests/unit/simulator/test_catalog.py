from pathlib import Path

import pytest

from dms.config.models import validate_acquisition_rules
from dms.simulator.catalog import (
    ONE_TANK,
    ONE_TANK_ACTIVE_HIGH,
    ONE_TANK_WITH_SENSORS,
    RELATION_OFFSET_S,
    SCENARIOS,
    TWO_SILOS,
    TWO_TANKS,
    build_catalog,
)
from dms.simulator.dms_config import acquisition_config
from dms.simulator.scenario import Scenario
from dms.simulator.scenario_model import Dispense, Refill

EXPECTED_RELATIONS = {
    "dispense-before-refill": ("before",),
    "dispense-after-refill": ("after",),
    "dispense-meets-refill": ("meets",),
    "refill-meets-dispense": ("met_by",),
    "dispense-front-refill": ("overlaps",),
    "dispense-inner-refill": ("during",),
    "dispense-back-refill": ("overlapped_by",),
    "dispense-starts-with-refill": ("starts",),
    "dispense-ends-with-refill": ("finishes",),
    "dispense-multi-inner-refill": ("during", "during", "during"),
    "dispense-front-multi-inner-back-refill": ("overlaps", "during", "during", "overlapped_by"),
}
OTHER_TANK_SUFFIX = "-other-tank"
OVERLAPPING_RELATIONS = {
    (-1, -1): "overlaps",
    (0, -1): "starts",
    (1, -1): "during",
    (0, 0): "equals",
    (1, 0): "finishes",
    (1, 1): "overlapped_by",
    (-1, 0): "finished_by",
    (-1, 1): "contains",
    (0, 1): "started_by",
}


def sign(value: float) -> int:
    return (value > 0) - (value < 0)


def allen_relation(dispense: Dispense, refill: Refill) -> str:
    if dispense.end_s <= refill.start_s:
        return "meets" if dispense.end_s == refill.start_s else "before"
    if dispense.start_s >= refill.end_s:
        return "met_by" if dispense.start_s == refill.end_s else "after"
    start_order = sign(dispense.start_s - refill.start_s)
    end_order = sign(dispense.end_s - refill.end_s)
    return OVERLAPPING_RELATIONS[start_order, end_order]


def relation_dispenses(scenario: Scenario) -> list[Dispense]:
    return sorted(
        (
            event
            for event in scenario.events
            if isinstance(event, Dispense) and event.start_s >= RELATION_OFFSET_S
        ),
        key=lambda event: event.start_s,
    )


def run_up_tanks(scenario: Scenario) -> list[int]:
    return [
        event.tank_id
        for event in scenario.events
        if isinstance(event, Dispense) and event.end_s < RELATION_OFFSET_S
    ]


def relation_of(scenario: Scenario) -> tuple[str, ...]:
    refill = next(event for event in scenario.events if isinstance(event, Refill))
    return tuple(allen_relation(dispense, refill) for dispense in relation_dispenses(scenario))


def test_catalog_has_expected_size() -> None:
    assert len(SCENARIOS) == 43


@pytest.mark.parametrize("name", EXPECTED_RELATIONS)
def test_relations_on_one_tank(name: str) -> None:
    scenario = SCENARIOS[name]

    assert relation_of(scenario) == EXPECTED_RELATIONS[name]
    assert {event.tank_id for event in scenario.events} == {1}
    assert run_up_tanks(scenario) == [1, 1, 1]
    assert scenario.layout is ONE_TANK


@pytest.mark.parametrize("name", EXPECTED_RELATIONS)
def test_relations_on_two_tanks_of_one_silo(name: str) -> None:
    scenario = SCENARIOS[f"{name}{OTHER_TANK_SUFFIX}"]

    assert relation_of(scenario) == EXPECTED_RELATIONS[name]
    assert {event.tank_id for event in relation_dispenses(scenario)} == {1}
    assert {event.tank_id for event in scenario.events if isinstance(event, Refill)} == {2}
    assert run_up_tanks(scenario) == [1, 1, 1, 2, 2, 2]
    assert scenario.layout is TWO_TANKS


def test_tanks_of_two_tank_relations_dispense_at_different_rates() -> None:
    scenario = SCENARIOS["dispense-inner-refill-other-tank"]

    rates = {
        event.tank_id: event.mass_kg / (event.end_s - event.start_s)
        for event in scenario.events
        if isinstance(event, Dispense)
    }

    assert rates[1] != rates[2]


@pytest.mark.parametrize(
    "name", ["two-silos-concurrent-dispenses", "two-silos-refill-and-dispense"]
)
def test_two_silo_scenarios_touch_both_silos(name: str) -> None:
    scenario = SCENARIOS[name]

    silos = {scenario.layout.silo_of(event.tank_id).id for event in scenario.events}

    assert silos == {1, 2}
    assert scenario.layout is TWO_SILOS


@pytest.mark.parametrize(
    "name", ["dispense-both-tanks-concurrent", "refill-with-concurrent-dispenses-both-tanks"]
)
def test_rule_violation_scenarios_overlap_dispenses_on_both_tanks(name: str) -> None:
    scenario = SCENARIOS[name]
    first, second = (event for event in scenario.events if isinstance(event, Dispense))

    assert scenario.allow_rule_violations
    assert scenario.layout is TWO_TANKS
    assert {first.tank_id, second.tank_id} == {1, 2}
    assert first.start_s < second.end_s
    assert second.start_s < first.end_s


def test_special_layouts_are_used() -> None:
    assert SCENARIOS["dispense-single-active-high"].layout is ONE_TANK_ACTIVE_HIGH
    assert SCENARIOS["dispense-single-with-sensors"].layout is ONE_TANK_WITH_SENSORS
    assert len(ONE_TANK_WITH_SENSORS.board.sensors) == 2


TEMPERATURE_SCENARIOS = [name for name in SCENARIOS if name.startswith("temperatures-")]


def test_temperature_scenarios_are_in_the_catalogue() -> None:
    assert TEMPERATURE_SCENARIOS == [
        "temperatures-rising",
        "temperatures-ambient-sensor",
        "temperatures-sensor-errors",
        "temperatures-out-of-range",
        "temperatures-sensor-missing-and-back",
        "temperatures-unknown-sensor",
    ]


def test_ambient_scenario_has_a_sensor_without_a_silo() -> None:
    sensors = SCENARIOS["temperatures-ambient-sensor"].layout.board.sensors

    assert [(sensor.silo_id, sensor.leg) for sensor in sensors] == [(1, 1), (None, None)]


def test_unknown_sensor_scenario_has_a_sensor_outside_the_configuration() -> None:
    scenario = SCENARIOS["temperatures-unknown-sensor"]

    config = acquisition_config(scenario.layout, Path("/tmp/dms"))

    assert [sensor.id for sensor in scenario.layout.board.sensors] == [1, 2]
    assert [sensor.id for sensor in config.temperature_sensors] == [1]


def test_duplicate_scenario_names_are_rejected() -> None:
    scenario = SCENARIOS["idle"]

    with pytest.raises(ValueError, match="duplicate scenario name 'idle'"):
        build_catalog([scenario, scenario])


def test_every_layout_gives_valid_acquisition_config() -> None:
    for layout in (ONE_TANK, TWO_TANKS, TWO_SILOS, ONE_TANK_ACTIVE_HIGH, ONE_TANK_WITH_SENSORS):
        assert validate_acquisition_rules(acquisition_config(layout, Path("/tmp/dms"))) == []
