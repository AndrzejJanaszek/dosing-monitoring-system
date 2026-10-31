import dataclasses
from dataclasses import dataclass
from uuid import UUID

from dms.domain.events import EventKind, StartedEvent


@dataclass(frozen=True, slots=True, kw_only=True)
class RuleViolation:
    silo_id: int
    kind: EventKind
    event_id: UUID
    tank_id: int
    other_event_id: UUID
    other_tank_id: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Overlap:
    partner_id: UUID
    partner_tank_id: int
    partner_kind: EventKind
    partner_start_known: bool
    partner_rule_violation: bool
    start_mono_ns: int | None
    end_mono_ns: int
    end_known: bool

    @property
    def duration_ns(self) -> int | None:
        if self.start_mono_ns is None:
            return None
        return self.end_mono_ns - self.start_mono_ns


@dataclass(frozen=True, slots=True, kw_only=True)
class _TrackedEvent:
    event_id: UUID
    tank_id: int
    kind: EventKind
    start_mono_ns: int | None
    rule_violation: bool = False
    is_open: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class _Pair:
    first_id: UUID
    second_id: UUID
    start_mono_ns: int | None
    end_mono_ns: int | None = None
    end_known: bool = False

    def involves(self, event_id: UUID) -> bool:
        return event_id in (self.first_id, self.second_id)

    def other_than(self, event_id: UUID) -> UUID:
        return self.second_id if event_id == self.first_id else self.first_id


class CollisionTracker:
    def __init__(self, silo_id: int) -> None:
        self._silo_id = silo_id
        self._events: dict[UUID, _TrackedEvent] = {}
        self._pairs: list[_Pair] = []

    def on_started(self, event: StartedEvent, start_mono_ns: int | None) -> list[RuleViolation]:
        started = _TrackedEvent(
            event_id=event.event_id,
            tank_id=event.tank_id,
            kind=event.kind,
            start_mono_ns=start_mono_ns,
        )
        violations: list[RuleViolation] = []
        for other in [tracked for tracked in self._events.values() if tracked.is_open]:
            self._pairs.append(
                _Pair(
                    first_id=other.event_id,
                    second_id=started.event_id,
                    start_mono_ns=_later(other.start_mono_ns, start_mono_ns),
                )
            )
            if other.kind is started.kind and other.tank_id != started.tank_id:
                violations.append(self._violation(started, other))
                started = dataclasses.replace(started, rule_violation=True)
                self._events[other.event_id] = dataclasses.replace(other, rule_violation=True)

        self._events[started.event_id] = started
        return violations

    def on_closed(self, event_id: UUID, end_mono_ns: int, *, edge_known: bool) -> list[Overlap]:
        self._events[event_id] = dataclasses.replace(self._events[event_id], is_open=False)
        self._pairs = [
            _ended(pair, end_mono_ns, edge_known=edge_known) if pair.involves(event_id) else pair
            for pair in self._pairs
        ]

        overlaps = [
            self._overlap_seen_by(event_id, pair)
            for pair in self._pairs
            if pair.involves(event_id)
        ]

        self._forget_finished()
        return overlaps

    def _violation(self, started: _TrackedEvent, other: _TrackedEvent) -> RuleViolation:
        return RuleViolation(
            silo_id=self._silo_id,
            kind=started.kind,
            event_id=started.event_id,
            tank_id=started.tank_id,
            other_event_id=other.event_id,
            other_tank_id=other.tank_id,
        )

    def _overlap_seen_by(self, event_id: UUID, pair: _Pair) -> Overlap:
        partner = self._events[pair.other_than(event_id)]
        end_mono_ns = pair.end_mono_ns
        if end_mono_ns is None:
            raise ValueError(f"overlap of event {event_id} has no end")
        return Overlap(
            partner_id=partner.event_id,
            partner_tank_id=partner.tank_id,
            partner_kind=partner.kind,
            partner_start_known=partner.start_mono_ns is not None,
            partner_rule_violation=partner.rule_violation,
            start_mono_ns=pair.start_mono_ns,
            end_mono_ns=end_mono_ns,
            end_known=pair.end_known,
        )

    def _forget_finished(self) -> None:
        self._pairs = [
            pair
            for pair in self._pairs
            if self._events[pair.first_id].is_open or self._events[pair.second_id].is_open
        ]
        referenced = {
            event_id for pair in self._pairs for event_id in (pair.first_id, pair.second_id)
        }
        self._events = {
            event_id: tracked
            for event_id, tracked in self._events.items()
            if tracked.is_open or event_id in referenced
        }


def _later(first_ns: int | None, second_ns: int | None) -> int | None:
    if first_ns is None:
        return second_ns
    if second_ns is None:
        return first_ns
    return max(first_ns, second_ns)


def _ended(pair: _Pair, end_mono_ns: int, *, edge_known: bool) -> _Pair:
    if pair.end_mono_ns is not None:
        return pair
    return dataclasses.replace(pair, end_mono_ns=end_mono_ns, end_known=edge_known)
