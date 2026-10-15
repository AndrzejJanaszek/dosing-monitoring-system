from dataclasses import dataclass
from typing import Literal
from uuid import UUID

type EventKind = Literal["dispense", "refill"]
type StartQuality = Literal["fresh", "stale_reading", "unknown"]
type EndQuality = Literal["fresh", "stale_reading", "signal_lost", "service_stopped"]


@dataclass(frozen=True, slots=True)
class StartedEvent:
    event_id: UUID
    tank_id: int
    kind: EventKind
    start_wall_ns: int
    start_value_kg: int | None
    start_quality: StartQuality


@dataclass(frozen=True, slots=True)
class ClosedEvent:
    event_id: UUID
    tank_id: int
    kind: EventKind
    start_wall_ns: int
    start_value_kg: int | None
    end_wall_ns: int
    end_value_kg: int | None
    duration_ns: int | None
    start_quality: StartQuality
    end_quality: EndQuality

    @property
    def status(self) -> Literal["completed", "incomplete"]:
        if self.start_quality == "fresh" and self.end_quality == "fresh":
            return "completed"
        return "incomplete"
