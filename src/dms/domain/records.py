from dataclasses import dataclass

from dms.domain.events import ClosedEvent, StartedEvent


@dataclass(frozen=True, slots=True)
class MeterRecord:
    silo_id: int
    wall_ns: int
    value_kg: int


type WriterRecord = MeterRecord | StartedEvent | ClosedEvent
