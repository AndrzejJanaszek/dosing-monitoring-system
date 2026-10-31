from collections.abc import Callable, Mapping, Sequence
from itertools import count
from uuid import UUID

from dms.domain.rate_history import RateSample
from dms.domain.silo import Silo
from dms.domain.temperatures import TemperatureSensors
from dms.messages import TemperatureEntry, TemperatureReadings
from dms.units import NS_PER_S

MAX_READING_AGE_NS = NS_PER_S
MAX_SIGNAL_AGE_NS = NS_PER_S
READING_CACHE_WINDOW_NS = 60 * NS_PER_S
SENSOR_ADDRESS = "28A8F126AB240B1C"
SENSOR_ID = 3
OTHER_ADDRESS = "28FF4A7C61160398"
WALL_OFFSET_NS = 1_000
RATE_HISTORY_CAPACITY = 3


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
    rate_samples: Mapping[int, Sequence[RateSample]] | None = None,
    rate_history_capacity: int = RATE_HISTORY_CAPACITY,
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
        rate_samples=rate_samples if rate_samples is not None else {},
        rate_history_capacity=rate_history_capacity,
    )


def build_temperature_sensors(
    sensor_id_by_address: Mapping[str, int] | None = None,
    *,
    record_interval_ns: int = NS_PER_S,
    max_reading_age_ns: int = 5 * NS_PER_S,
    tick_interval_ns: int = NS_PER_S,
    min_valid_c: float = -40.0,
    max_valid_c: float = 80.0,
    started_mono_ns: int = 0,
) -> TemperatureSensors:
    return TemperatureSensors(
        sensor_id_by_address=sensor_id_by_address
        if sensor_id_by_address is not None
        else {SENSOR_ADDRESS: SENSOR_ID},
        record_interval_ns=record_interval_ns,
        max_reading_age_ns=max_reading_age_ns,
        tick_interval_ns=tick_interval_ns,
        min_valid_c=min_valid_c,
        max_valid_c=max_valid_c,
        started_mono_ns=started_mono_ns,
    )


def temperature_readings(
    at_s: float, *entries: tuple[str, float | None, str | None]
) -> TemperatureReadings:
    return TemperatureReadings(
        entries=tuple(TemperatureEntry(*entry) for entry in entries),
        wall_ns=WALL_OFFSET_NS + round(at_s * NS_PER_S),
        mono_ns=round(at_s * NS_PER_S),
    )
