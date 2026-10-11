from dms.domain.records import MeterRecord
from dms.domain.silo import Silo
from dms.messages import MeterReading, Tick

SECOND_NS = 1_000_000_000
MAX_AGE_NS = SECOND_NS


def reading(mono_s: float, value_kg: int) -> MeterReading:
    mono_ns = round(mono_s * SECOND_NS)
    return MeterReading("m1", value_kg, mono_ns + 1000, mono_ns)


def tick(mono_s: float) -> Tick:
    return Tick(0, round(mono_s * SECOND_NS))


def test_fresh_reading_gives_record_with_reading_timestamp() -> None:
    silo = Silo(3, MAX_AGE_NS)
    silo.on_reading(reading(10.0, 500))

    assert silo.on_tick(tick(10.4)) == MeterRecord(3, 10 * SECOND_NS + 1000, 500)


def test_no_reading_gives_no_record() -> None:
    assert Silo(1, MAX_AGE_NS).on_tick(tick(1)) is None


def test_stale_reading_gives_no_record() -> None:
    silo = Silo(1, MAX_AGE_NS)
    silo.on_reading(reading(10.0, 500))

    assert silo.on_tick(tick(11.5)) is None


def test_reading_exactly_at_age_limit_is_still_fresh() -> None:
    silo = Silo(1, MAX_AGE_NS)
    silo.on_reading(reading(10.0, 500))

    assert silo.on_tick(tick(11.0)) is not None


def test_same_reading_is_not_emitted_twice() -> None:
    silo = Silo(1, MAX_AGE_NS)
    silo.on_reading(reading(10.0, 500))

    assert silo.on_tick(tick(10.2)) is not None
    assert silo.on_tick(tick(10.8)) is None


def test_new_reading_after_emission_is_emitted() -> None:
    silo = Silo(1, MAX_AGE_NS)
    silo.on_reading(reading(10.0, 500))
    silo.on_tick(tick(10.2))
    silo.on_reading(reading(10.9, 520))

    record = silo.on_tick(tick(11.0))

    assert record is not None
    assert record.value_kg == 520


def test_tick_uses_the_latest_reading_when_several_arrived() -> None:
    silo = Silo(1, MAX_AGE_NS)
    for index, mono_s in enumerate((10.1, 10.3, 10.5)):
        silo.on_reading(reading(mono_s, 100 + index))

    record = silo.on_tick(tick(10.6))

    assert record is not None
    assert record.value_kg == 102
