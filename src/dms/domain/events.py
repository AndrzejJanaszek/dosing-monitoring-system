from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class EventKind(StrEnum):
    DISPENSE = "dispense"
    REFILL = "refill"


class StartQuality(StrEnum):
    FRESH = "fresh"
    STALE_READING = "stale_reading"
    UNKNOWN = "unknown"


class EndQuality(StrEnum):
    FRESH = "fresh"
    STALE_READING = "stale_reading"
    SIGNAL_LOST = "signal_lost"
    SERVICE_STOPPED = "service_stopped"
    SERVICE_CRASHED = "service_crashed"
    RECORD_REJECTED = "record_rejected"


class EventStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True, slots=True, kw_only=True)
class StartedEvent:
    event_id: UUID
    tank_id: int
    kind: EventKind
    start_wall_ns: int
    start_value_kg: int | None
    start_quality: StartQuality


@dataclass(frozen=True, slots=True, kw_only=True)
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
    def status(self) -> EventStatus:
        if self.start_quality is StartQuality.FRESH and self.end_quality is EndQuality.FRESH:
            return EventStatus.COMPLETED
        return EventStatus.INCOMPLETE
