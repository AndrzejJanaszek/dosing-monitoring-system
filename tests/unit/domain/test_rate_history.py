from uuid import UUID

import pytest

from dms.domain.rate_history import RateHistory, RateSample, RateSampleRejected, rate_sample_of
from dms.units import NS_PER_MS, NS_PER_S
from tests.rate_history_cases import RATE_CASES, RateCase, case_record


@pytest.mark.parametrize("case", RATE_CASES, ids=[case.name for case in RATE_CASES])
def test_clean_dispense_criteria_and_safety_check(case: RateCase) -> None:
    outcome = rate_sample_of(case.record)

    if case.outcome is None:
        assert outcome is None
    else:
        assert isinstance(outcome, case.outcome)


def test_sample_holds_the_mass_and_duration_of_the_dispense() -> None:
    assert rate_sample_of(case_record(1)) == RateSample(
        event_id=UUID(int=1), mass_kg=600, duration_ns=12 * NS_PER_S
    )


def test_negative_duration_is_rejected() -> None:
    record = case_record(1, duration_ms=-250)

    assert rate_sample_of(record) == RateSampleRejected(
        event_id=UUID(int=1), tank_id=1, mass_kg=600, duration_ns=-250 * NS_PER_MS
    )


def sample(number: int) -> RateSample:
    return RateSample(event_id=UUID(int=number), mass_kg=500, duration_ns=10 * NS_PER_S)


def test_history_keeps_the_latest_samples_up_to_its_capacity() -> None:
    history = RateHistory(3, [sample(1), sample(2)])

    history.add(sample(3))
    history.add(sample(4))

    assert history.samples() == [sample(2), sample(3), sample(4)]


def test_history_loaded_with_more_samples_than_capacity_keeps_the_latest() -> None:
    assert RateHistory(2, [sample(1), sample(2), sample(3)]).samples() == [sample(2), sample(3)]
