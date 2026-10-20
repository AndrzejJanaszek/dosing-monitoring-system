from itertools import islice

from dms.simulator.layout import (
    ErrorCode,
    FixedValue,
    Missing,
    PlantLayout,
    SensorFault,
    SignalBoard,
    SiloLayout,
    TemperatureSensor,
)
from dms.simulator.timeline import (
    MeterSample,
    PinsSample,
    SimulatedReading,
    TemperaturesSample,
    samples_from,
    scenario_samples,
)
from dms.units import NS_PER_S
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

    meter_times = [sample.at_ns for sample in samples if isinstance(sample, MeterSample)]
    pins_times = [sample.at_ns for sample in samples if isinstance(sample, PinsSample)]
    temperature_times = [
        sample.at_ns for sample in samples if isinstance(sample, TemperaturesSample)
    ]
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
        sample.value_kg
        for sample in scenario_samples(scenario_with(dispense()))
        if isinstance(sample, MeterSample)
    ]

    assert values[0] == 20_000
    assert values[-1] == 18_500
    assert values == sorted(values, reverse=True)


def test_samples_from_shifts_the_grid_and_applies_state_time() -> None:
    scenario = scenario_with(dispense())

    samples = list(islice(samples_from(scenario, 5 * NS_PER_S, lambda _t_ns: 0), 3))

    assert [sample.at_ns for sample in samples] == [5 * NS_PER_S] * 3
    assert isinstance(samples[0], MeterSample)
    assert samples[0].value_kg == 20_000


def test_state_time_can_hold_the_final_state() -> None:
    scenario = scenario_with(dispense())

    def hold(t_ns: int) -> int:
        return min(t_ns, scenario.duration_ns)

    late = [
        sample
        for sample in islice(samples_from(scenario, 0, hold), 5000)
        if isinstance(sample, MeterSample) and sample.at_ns > 100 * NS_PER_S
    ]

    assert {sample.value_kg for sample in late} == {18_500}


def test_temperature_sample_carries_sensor_readings() -> None:
    layout = PlantLayout(
        (SiloLayout(id=1, tanks=(tank(1, 4, 5),)),),
        SignalBoard(sensors=(TemperatureSensor(id=1, address="28A8F126AB240B1C", start_c=21.5),)),
    )

    sample = next(
        sample
        for sample in scenario_samples(scenario_with(dispense(), layout=layout))
        if isinstance(sample, TemperaturesSample)
    )

    assert sample.readings == (SimulatedReading("28A8F126AB240B1C", 21.5, None),)


ADDRESS = "28A8F126AB240B1C"
OTHER_ADDRESS = "28FF4A7C61160398"


def temperature_samples(*sensors: TemperatureSensor) -> list[TemperaturesSample]:
    layout = PlantLayout((SiloLayout(id=1, tanks=(tank(1, 4, 5),)),), SignalBoard(sensors=sensors))
    return [
        sample
        for sample in scenario_samples(scenario_with(dispense(), layout=layout))
        if isinstance(sample, TemperaturesSample)
    ]


def test_temperature_rises_linearly_with_the_scenario_time() -> None:
    sensor = TemperatureSensor(id=1, address=ADDRESS, start_c=20.0, rate_c_per_min=6.0)

    samples = temperature_samples(sensor)

    assert [sample.readings[0].value_c for sample in samples[:3]] == [20.0, 20.1, 20.2]


def test_faults_replace_readings_only_inside_their_interval() -> None:
    sensor = TemperatureSensor(
        id=1,
        address=ADDRESS,
        start_c=20.0,
        faults=(
            SensorFault(start_s=1.0, end_s=2.0, kind=ErrorCode("read_failed")),
            SensorFault(start_s=3.0, end_s=4.0, kind=FixedValue(85.0)),
            SensorFault(start_s=5.0, end_s=6.0, kind=Missing()),
        ),
    )

    samples = temperature_samples(sensor)

    readings = {sample.at_ns // NS_PER_S: sample.readings for sample in samples}
    ok = SimulatedReading(ADDRESS, 20.0, None)
    assert readings[0] == (ok,)
    assert readings[1] == (SimulatedReading(ADDRESS, None, "read_failed"),)
    assert readings[2] == (ok,)
    assert readings[3] == (SimulatedReading(ADDRESS, 85.0, None),)
    assert readings[4] == (ok,)
    assert readings[5] == ()
    assert readings[6] == (ok,)


def test_fault_of_one_sensor_leaves_the_other_sensor_readable() -> None:
    faulty = TemperatureSensor(
        id=1,
        address=ADDRESS,
        start_c=20.0,
        faults=(SensorFault(start_s=0.0, end_s=2.0, kind=Missing()),),
    )
    healthy = TemperatureSensor(id=2, address=OTHER_ADDRESS, start_c=22.0)

    (first, *_) = temperature_samples(faulty, healthy)

    assert first.readings == (SimulatedReading(OTHER_ADDRESS, 22.0, None),)
