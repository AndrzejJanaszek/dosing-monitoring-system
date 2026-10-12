from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MeterRecord:
    silo_id: int
    wall_ns: int
    value_kg: int
