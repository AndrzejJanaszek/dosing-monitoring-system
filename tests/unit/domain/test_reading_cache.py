from dms.domain.reading_cache import ReadingCache
from dms.messages import MeterReading

SECOND_NS = 1_000_000_000


def reading(mono_s: float, value_kg: int = 0) -> MeterReading:
    return MeterReading("m1", value_kg, 0, round(mono_s * SECOND_NS))


def test_empty_cache_has_no_reading() -> None:
    assert ReadingCache().advance_to(10 * SECOND_NS) is None


def test_returns_latest_reading_not_after_the_given_time() -> None:
    cache = ReadingCache()
    for second in (1, 2, 3):
        cache.add(reading(second, value_kg=second))

    found = cache.advance_to(round(2.5 * SECOND_NS))

    assert found is not None
    assert found.value_kg == 2


def test_reading_exactly_at_the_given_time_is_included() -> None:
    cache = ReadingCache()
    cache.add(reading(5, value_kg=5))

    found = cache.advance_to(5 * SECOND_NS)

    assert found is not None
    assert found.value_kg == 5


def test_reading_after_the_given_time_is_ignored_and_kept() -> None:
    cache = ReadingCache()
    cache.add(reading(5, value_kg=5))

    assert cache.advance_to(4 * SECOND_NS) is None
    found = cache.advance_to(6 * SECOND_NS)
    assert found is not None
    assert found.value_kg == 5


def test_readings_older_than_the_returned_one_are_dropped() -> None:
    cache = ReadingCache()
    for second in (1, 2, 3, 4):
        cache.add(reading(second, value_kg=second))

    cache.advance_to(round(2.5 * SECOND_NS))

    assert len(cache) == 3
    found = cache.advance_to(round(2.5 * SECOND_NS))
    assert found is not None
    assert found.value_kg == 2


def test_last_reading_is_kept_for_later_ticks() -> None:
    cache = ReadingCache()
    cache.add(reading(1, value_kg=1))

    cache.advance_to(5 * SECOND_NS)
    found = cache.advance_to(6 * SECOND_NS)

    assert found is not None
    assert found.value_kg == 1
    assert len(cache) == 1
