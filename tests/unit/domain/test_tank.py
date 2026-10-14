from dms.domain.tank import SignalChange, Tank
from dms.messages import TankSignals


def signals(dispense: bool, refill: bool) -> TankSignals:
    return TankSignals(3, dispense=dispense, refill=refill)


def test_first_snapshot_reports_both_signals_with_unknown_previous_state() -> None:
    changes = Tank(3).on_signals(signals(False, True))

    assert changes == [
        SignalChange(3, "dispense", False, None),
        SignalChange(3, "refill", True, None),
    ]


def test_only_the_changed_signal_is_reported() -> None:
    tank = Tank(3)
    tank.on_signals(signals(False, False))

    assert tank.on_signals(signals(True, False)) == [SignalChange(3, "dispense", True, False)]


def test_unchanged_snapshot_reports_nothing() -> None:
    tank = Tank(3)
    tank.on_signals(signals(True, False))

    assert tank.on_signals(signals(True, False)) == []


def test_both_signals_changing_are_reported_dispense_first() -> None:
    tank = Tank(3)
    tank.on_signals(signals(False, False))

    assert tank.on_signals(signals(True, True)) == [
        SignalChange(3, "dispense", True, False),
        SignalChange(3, "refill", True, False),
    ]
