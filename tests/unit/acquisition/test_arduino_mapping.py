from dms.acquisition.arduino.mapping import SignalMapper
from dms.messages import TankSignals
from tests.unit.acquisition.builders import tank_config


def test_low_level_is_active_with_active_low_polarity() -> None:
    mapper = SignalMapper([tank_config(1, 4, 5, active_level=0)])

    assert mapper.signals({4: 0, 5: 1}) == (TankSignals(1, dispense=True, refill=False),)


def test_high_level_is_active_with_active_high_polarity() -> None:
    mapper = SignalMapper([tank_config(1, 4, 5, active_level=1)])

    assert mapper.signals({4: 0, 5: 1}) == (TankSignals(1, dispense=False, refill=True),)


def test_tanks_keep_the_configuration_order() -> None:
    mapper = SignalMapper([tank_config(2, 6, 7), tank_config(1, 4, 5)])

    signals = mapper.signals({4: 1, 5: 1, 6: 0, 7: 1})

    assert [item.tank_id for item in signals] == [2, 1]


def test_pins_outside_the_configuration_are_ignored() -> None:
    mapper = SignalMapper([tank_config(1, 4, 5)])

    assert mapper.signals({4: 1, 5: 1, 9: 0}) == (TankSignals(1, dispense=False, refill=False),)
    assert mapper.missing_pins({4: 1, 5: 1, 9: 0}) == frozenset()


def test_missing_pins_are_the_configured_ones_absent_from_the_frame() -> None:
    mapper = SignalMapper([tank_config(1, 4, 5), tank_config(2, 6, 7)])

    assert mapper.missing_pins({4: 1, 7: 0}) == frozenset({5, 6})
