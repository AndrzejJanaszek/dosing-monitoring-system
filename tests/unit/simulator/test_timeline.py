from itertools import islice

from dms.acquisition.clock import NS_PER_S
from dms.simulator.layout import PlantLayout, SignalBoard, SiloLayout, TemperatureSensor
from dms.simulator.timeline import (
    MeterSample,
    PinsSample,
    TemperaturesSample,
    samples_from,
    scenario_samples,
)
from tests.unit.simulator.builders import dispense, scenario_with, tank

METER_PERIOD_NS = 100_000_000
PINS_PERIOD_NS = 250_000_000


def test_samples_are_ordered_and_ties_follow_device_order() -> None:
    scenario = scenario_with(dispense())

    first = list(islice(scenario_samples(scenario), 4))

    assert [type(sample) for sample in first] == [
        MeterSample,
        PinsSample,
        TemperaturesSample,
        MeterSample,
    ]
    assert [sample.at_ns for sample in first] == [0, 0, 0, METER_PERIOD_NS]


def test_device_periods_follow_rates() -> None:
    samples = list(scenario_samples(scenario_with(dispense())))

    meter_times = [s.at_ns for s in samples if isinstance(s, MeterSample)]
    pins_times = [s.at_ns for s in samples if isinstance(s, PinsSample)]
    temperature_times = [s.at_ns for s in samples if isinstance(s, TemperaturesSample)]
    assert meter_times[:3] == [0, METER_PERIOD_NS, 2 * METER_PERIOD_NS]
    assert pins_times[:3] == [0, PINS_PERIOD_NS, 2 * PINS_PERIOD_NS]
    assert temperature_times[:3] == [0, NS_PER_S, 2 * NS_PER_S]


def test_scenario_samples_are_deterministic_and_finite() -> None:
    scenario = scenario_with(dispense())

    first = list(scenario_samples(scenario))
    second = list(scenario_samples(scenario))

    assert first == second
    assert first[-1].at_ns <= scenario.duration_ns
    assert max(sample.at_ns for sample in first) > scenario.duration_ns - NS_PER_S


def test_meter_values_follow_the_mass() -> None:
    values = [
        s.value_kg
        for s in scenario_samples(scenario_with(dispense()))
        if isinstance(s, MeterSample)
    ]

    assert values[0] == 20_000
    assert values[-1] == 18_500
    assert values == sorted(values, reverse=True)


def test_samples_from_shifts_the_grid_and_applies_state_time() -> None:
    scenario = scenario_with(dispense())

    samples = list(islice(samples_from(scenario, 5 * NS_PER_S, lambda t_ns: 0), 3))

    assert [sample.at_ns for sample in samples] == [5 * NS_PER_S] * 3
    assert isinstance(samples[0], MeterSample) and samples[0].value_kg == 20_000


def test_state_time_can_hold_the_final_state() -> None:
    scenario = scenario_with(dispense())

    def hold(t_ns: int) -> int:
        return min(t_ns, scenario.duration_ns)

    late = [
        s
        for s in islice(samples_from(scenario, 0, hold), 5000)
        if isinstance(s, MeterSample) and s.at_ns > 100 * NS_PER_S
    ]

    assert {s.value_kg for s in late} == {18_500}


def test_temperature_sample_carries_sensor_readings() -> None:
    layout = PlantLayout(
        (SiloLayout(1, (tank(1, 4, 5),)),),
        SignalBoard(sensors=(TemperatureSensor("28A8F126AB240B1C", 21.5),)),
    )

    sample = next(
        s
        for s in scenario_samples(scenario_with(dispense(), layout=layout))
        if isinstance(s, TemperaturesSample)
    )

    assert sample.readings == (("28A8F126AB240B1C", 21.5),)
