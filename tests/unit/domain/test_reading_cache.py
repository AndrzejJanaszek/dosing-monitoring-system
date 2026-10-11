from dms.domain.reading_cache import ReadingCache
from dms.messages import MeterReading

SECOND_NS = 1_000_000_000


def reading(mono_s: float, value_kg: int = 0) -> MeterReading:
    return MeterReading("m1", value_kg, 0, round(mono_s * SECOND_NS))


def test_empty_cache_has_no_reading() -> None:
    assert ReadingCache(60 * SECOND_NS).at_or_before(10 * SECOND_NS) is None


def test_returns_latest_reading_not_after_the_given_time() -> None:
    cache = ReadingCache(60 * SECOND_NS)
    for second in (1, 2, 3):
        cache.add(reading(second, value_kg=second))

    found = cache.at_or_before(round(2.5 * SECOND_NS))

    assert found is not None
    assert found.value_kg == 2


def test_reading_exactly_at_the_given_time_is_included() -> None:
    cache = ReadingCache(60 * SECOND_NS)
    cache.add(reading(5, value_kg=5))

    found = cache.at_or_before(5 * SECOND_NS)

    assert found is not None
    assert found.value_kg == 5


def test_reading_after_the_given_time_is_ignored() -> None:
    cache = ReadingCache(60 * SECOND_NS)
    cache.add(reading(5))

    assert cache.at_or_before(4 * SECOND_NS) is None


def test_readings_older_than_the_window_are_dropped() -> None:
    cache = ReadingCache(10 * SECOND_NS)
    cache.add(reading(1, value_kg=1))
    cache.add(reading(20, value_kg=20))

    assert cache.at_or_before(5 * SECOND_NS) is None
    found = cache.at_or_before(20 * SECOND_NS)
    assert found is not None
    assert found.value_kg == 20
