from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class MeterReading:
    meter_id: str
    value_kg: int
    wall_ns: int
    mono_ns: int


@dataclass(frozen=True, slots=True)
class TankSignals:
    tank_id: int
    dispense: bool
    refill: bool


@dataclass(frozen=True, slots=True)
class SignalStates:
    tanks: tuple[TankSignals, ...]
    wall_ns: int
    mono_ns: int


@dataclass(frozen=True, slots=True)
class TemperatureEntry:
    address: str
    value_c: float | None
    error_code: str | None


@dataclass(frozen=True, slots=True)
class TemperatureReadings:
    entries: tuple[TemperatureEntry, ...]
    wall_ns: int
    mono_ns: int


@dataclass(frozen=True, slots=True)
class Tick:
    wall_ns: int
    mono_ns: int


type EngineMessage = MeterReading | SignalStates | TemperatureReadings | Tick
