import heapq
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import partial

from dms.simulator.layout import (
    ErrorCode,
    FixedValue,
    Missing,
    SiloLayout,
    TemperatureSensor,
)
from dms.simulator.plant_state import indication_kg, pin_levels, silo_mass_kg
from dms.simulator.scenario_model import ScenarioData
from dms.units import NS_PER_S


@dataclass(frozen=True, slots=True)
class MeterSample:
    at_ns: int
    meter_id: str
    value_kg: int


@dataclass(frozen=True, slots=True)
class PinsSample:
    at_ns: int
    board_id: str
    levels: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class SimulatedReading:
    address: str
    value_c: float | None
    error_code: str | None


@dataclass(frozen=True, slots=True)
class TemperaturesSample:
    at_ns: int
    board_id: str
    readings: tuple[SimulatedReading, ...]


type Sample = MeterSample | PinsSample | TemperaturesSample

type SampleBuilder = Callable[[ScenarioData, int, int], Sample]


@dataclass(frozen=True, slots=True)
class _Device:
    period_ns: int
    build: SampleBuilder


def samples_from(
    scenario: ScenarioData, start_ns: int, state_time: Callable[[int], int]
) -> Iterator[Sample]:
    devices = _devices(scenario)
    queue = [(start_ns, order, 0) for order in range(len(devices))]
    heapq.heapify(queue)
    while True:
        at_ns, order, index = queue[0]
        device = devices[order]
        yield device.build(scenario, at_ns, state_time(at_ns - start_ns))
        next_index = index + 1
        heapq.heapreplace(queue, (start_ns + next_index * device.period_ns, order, next_index))


def scenario_samples(scenario: ScenarioData) -> Iterator[Sample]:
    for sample in samples_from(scenario, 0, _same_time):
        if sample.at_ns > scenario.duration_ns:
            return
        yield sample


def _same_time(t_ns: int) -> int:
    return t_ns


def _period_ns(period_s: float) -> int:
    return round(period_s * NS_PER_S)


def _devices(scenario: ScenarioData) -> list[_Device]:
    board = scenario.layout.board
    meters = [
        _Device(_period_ns(1 / silo.meter.rate_hz), partial(_meter_sample, silo))
        for silo in scenario.layout.silos
    ]
    pins = _Device(_period_ns(board.pins_period_s), _pins_sample)
    temperatures = _Device(_period_ns(board.temperatures_period_s), _temperatures_sample)
    return [*meters, pins, temperatures]


def _meter_sample(silo: SiloLayout, scenario: ScenarioData, at_ns: int, state_ns: int) -> Sample:
    mass_kg = silo_mass_kg(scenario, silo.id, state_ns)
    return MeterSample(at_ns, silo.meter_id, indication_kg(mass_kg, silo.meter))


def _pins_sample(scenario: ScenarioData, at_ns: int, state_ns: int) -> Sample:
    return PinsSample(at_ns, scenario.layout.board.id, pin_levels(scenario, state_ns))


def _temperatures_sample(scenario: ScenarioData, at_ns: int, state_ns: int) -> Sample:
    board = scenario.layout.board
    readings = tuple(
        reading
        for sensor in board.sensors
        if (reading := _sensor_reading(sensor, state_ns)) is not None
    )
    return TemperaturesSample(at_ns, board.id, readings)


def _sensor_reading(sensor: TemperatureSensor, state_ns: int) -> SimulatedReading | None:
    match sensor.fault_at(state_ns):
        case Missing():
            return None
        case ErrorCode(code=code):
            return SimulatedReading(sensor.address, None, code)
        case FixedValue(value_c=value_c):
            return SimulatedReading(sensor.address, value_c, None)
        case None:
            return SimulatedReading(sensor.address, sensor.value_c(state_ns), None)
