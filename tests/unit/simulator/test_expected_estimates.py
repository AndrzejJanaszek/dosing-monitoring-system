from dms.domain.estimates import MissingReason
from dms.domain.events import EndQuality, EventKind, StartQuality
from dms.simulator.expected_estimates import expected_estimates
from dms.simulator.expected_events import ExpectedEvent
from dms.simulator.scenario import Scenario
from dms.units import NS_PER_S
from tests.unit.simulator.builders import dispense, refill, scenario_with, two_tank_layout


def expected(
    kind: EventKind,
    start_s: float,
    end_s: float,
    *,
    tank_id: int = 1,
    collision: bool = False,
    rule_violation: bool = False,
    start_quality: StartQuality = StartQuality.FRESH,
) -> ExpectedEvent:
    return ExpectedEvent(
        tank_id=tank_id,
        kind=kind,
        start_ns=round(start_s * NS_PER_S),
        end_ns=round(end_s * NS_PER_S),
        start_value_kg=None if start_quality is StartQuality.UNKNOWN else 10_000,
        end_value_kg=9_000,
        start_quality=start_quality,
        end_quality=EndQuality.FRESH,
        collision=collision,
        rule_violation=rule_violation,
    )


RUN_UP = [dispense(10, 40), dispense(50, 80)]
RUN_UP_EVENTS = [expected(EventKind.DISPENSE, 10, 40), expected(EventKind.DISPENSE, 50, 80)]


def test_collided_dispense_after_a_run_up_is_expected_at_its_true_mass() -> None:
    scenario = scenario_with(*RUN_UP, refill(100, 400), dispense(150, 180))
    collided = expected(EventKind.DISPENSE, 150, 180, collision=True)
    events = [*RUN_UP_EVENTS, expected(EventKind.REFILL, 100, 400, collision=True), collided]

    estimate = expected_estimates(scenario, events, n=2)[collided]

    assert (estimate.missing_reason, estimate.true_kg) == (None, 1_500)
    assert 0 < estimate.tolerance_kg < 150


def test_refill_over_a_dispense_with_an_unknown_start_is_expected_at_its_true_mass() -> None:
    scenario = scenario_with(*RUN_UP, dispense(90, 130), refill(100, 400))
    collided_refill = expected(EventKind.REFILL, 100, 400, collision=True)
    events = [
        *RUN_UP_EVENTS,
        expected(EventKind.DISPENSE, 85, 130, collision=True, start_quality=StartQuality.UNKNOWN),
        collided_refill,
    ]

    estimate = expected_estimates(scenario, events, n=2)[collided_refill]

    assert (estimate.missing_reason, estimate.true_kg) == (None, 6_000)
    assert estimate.tolerance_kg > 0


def test_violation_starting_after_the_refill_ended_does_not_reach_the_refill() -> None:
    scenario = Scenario(
        name="test",
        layout=two_tank_layout(),
        start_masses_kg=None,
        events=(refill(10, 100), dispense(80, 110), dispense(105, 135, tank_id=2)),
        allow_rule_violations=True,
    )
    collided_refill = expected(EventKind.REFILL, 10, 100, collision=True)
    events = [
        collided_refill,
        expected(EventKind.DISPENSE, 80, 110, collision=True, rule_violation=True),
        expected(EventKind.DISPENSE, 105, 135, tank_id=2, collision=True, rule_violation=True),
    ]

    estimate = expected_estimates(scenario, events, n=2)[collided_refill]

    assert estimate.missing_reason is MissingReason.NO_RATE_HISTORY


def test_events_without_collision_have_no_expected_estimate() -> None:
    scenario = scenario_with(*RUN_UP)

    assert expected_estimates(scenario, RUN_UP_EVENTS, n=2) == {}
