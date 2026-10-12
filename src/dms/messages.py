from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MeterReading:
    meter_id: str
    value_kg: int
    wall_ns: int
    mono_ns: int


@dataclass(frozen=True, slots=True)
class Tick:
    wall_ns: int
    mono_ns: int


type EngineMessage = MeterReading | Tick
