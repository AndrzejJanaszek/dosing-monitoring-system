from collections.abc import Sequence

from dms.domain.collisions import Overlap
from dms.domain.events import ClosedEvent
from dms.domain.records import EventRecord


def finalize_event(event: ClosedEvent, overlaps: Sequence[Overlap]) -> EventRecord:
    return EventRecord(
        event=event,
        collision=bool(overlaps),
        rule_violation=any(overlap.partner_kind is event.kind for overlap in overlaps),
    )
