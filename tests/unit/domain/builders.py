from collections.abc import Callable
from itertools import count
from uuid import UUID

from dms.domain.silo import Silo
from dms.units import NS_PER_S

MAX_READING_AGE_NS = NS_PER_S
MAX_SIGNAL_AGE_NS = NS_PER_S
READING_CACHE_WINDOW_NS = 60 * NS_PER_S


def sequential_ids() -> Callable[[], UUID]:
    numbers = count(1)
    return lambda: UUID(int=next(numbers))


def build_silo(
    silo_id: int = 1,
    *,
    tank_ids: tuple[int, ...] = (),
    max_reading_age_ns: int = MAX_READING_AGE_NS,
    max_signal_age_ns: int = MAX_SIGNAL_AGE_NS,
    started_wall_ns: int = 0,
    started_mono_ns: int = 0,
    new_event_id: Callable[[], UUID] | None = None,
) -> Silo:
    return Silo(
        silo_id,
        max_reading_age_ns=max_reading_age_ns,
        max_signal_age_ns=max_signal_age_ns,
        reading_cache_window_ns=READING_CACHE_WINDOW_NS,
        tank_ids=tank_ids,
        new_event_id=new_event_id if new_event_id is not None else sequential_ids(),
        started_wall_ns=started_wall_ns,
        started_mono_ns=started_mono_ns,
    )
