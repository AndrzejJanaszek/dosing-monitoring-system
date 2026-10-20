from dms.domain.reading_cache import ReadingCache
from dms.messages import MeterReading
from dms.units import NS_PER_S

WINDOW_NS = 10 * NS_PER_S


def reading(mono_s: float, value_kg: int = 0) -> MeterReading:
    return MeterReading(
        meter_id="m1", value_kg=value_kg, wall_ns=0, mono_ns=round(mono_s * NS_PER_S)
    )


def build(*seconds: float) -> ReadingCache:
    cache = ReadingCache(WINDOW_NS)
    for second in seconds:
        cache.add(reading(second, value_kg=round(second)))
    return cache


def test_empty_cache_has_no_reading() -> None:
    assert ReadingCache(WINDOW_NS).at_or_before(10 * NS_PER_S) is None


def test_returns_latest_reading_not_after_the_given_time() -> None:
    found = build(1, 2, 3).at_or_before(round(2.5 * NS_PER_S))

    assert found is not None
    assert found.value_kg == 2


def test_reading_exactly_at_the_given_time_is_included() -> None:
    found = build(5).at_or_before(5 * NS_PER_S)

    assert found is not None
    assert found.value_kg == 5


def test_reading_after_the_given_time_is_ignored_and_kept() -> None:
    cache = build(5)

    assert cache.at_or_before(4 * NS_PER_S) is None
    found = cache.at_or_before(6 * NS_PER_S)
    assert found is not None
    assert found.value_kg == 5


def test_lookup_does_not_remove_readings() -> None:
    cache = build(1, 2, 3, 4)

    cache.at_or_before(round(2.5 * NS_PER_S))

    assert len(cache) == 4
    found = cache.at_or_before(round(1.5 * NS_PER_S))
    assert found is not None
    assert found.value_kg == 1


def test_reading_from_before_a_later_lookup_is_still_available() -> None:
    cache = build(1, 2)

    cache.at_or_before(5 * NS_PER_S)
    found = cache.at_or_before(round(1.5 * NS_PER_S))

    assert found is not None
    assert found.value_kg == 1


def test_readings_older_than_the_window_are_dropped_on_add() -> None:
    cache = build(1, 5, 12)

    assert len(cache) == 2
    assert cache.at_or_before(2 * NS_PER_S) is None


def test_reading_exactly_at_the_window_edge_is_kept() -> None:
    cache = build(2, 12)

    assert len(cache) == 2


def test_newest_reading_is_kept_after_a_long_silence() -> None:
    cache = build(1)
    cache.add(reading(100, value_kg=100))

    assert len(cache) == 1
    found = cache.at_or_before(200 * NS_PER_S)
    assert found is not None
    assert found.value_kg == 100


def test_out_of_order_reading_is_inserted_in_its_place() -> None:
    cache = build(1, 3, 2)

    found = cache.at_or_before(round(2.5 * NS_PER_S))

    assert found is not None
    assert found.value_kg == 2
    assert len(cache) == 3
