from dataclasses import dataclass

from dms.domain.events import ClosedEvent, StartedEvent
from dms.domain.temperature_error import TemperatureError


@dataclass(frozen=True, slots=True)
class MeterRecord:
    silo_id: int
    wall_ns: int
    value_kg: int


@dataclass(frozen=True, slots=True, kw_only=True)
class EventRecord:
    event: ClosedEvent
    collision: bool
    rule_violation: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class TemperatureRecord:
    sensor_id: int
    wall_ns: int
    value_c: float | None
    error: TemperatureError | None


@dataclass(frozen=True, slots=True, kw_only=True)
class UnknownSensorRecord:
    address: str
    wall_ns: int
    value_c: float | None
    error: TemperatureError | None


type WriterRecord = (
    MeterRecord | TemperatureRecord | UnknownSensorRecord | StartedEvent | EventRecord
)
