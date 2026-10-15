from collections.abc import Mapping, Sequence

from dms.config.models import TankConfig
from dms.messages import TankSignals


class SignalMapper:
    def __init__(self, tanks: Sequence[TankConfig]) -> None:
        self._tanks = tuple(tanks)
        self._configured_pins = frozenset(
            pin for tank in self._tanks for pin in (tank.dispense.pin, tank.refill.pin)
        )

    def missing_pins(self, levels: Mapping[int, int]) -> frozenset[int]:
        return self._configured_pins - levels.keys()

    def signals(self, levels: Mapping[int, int]) -> tuple[TankSignals, ...]:
        return tuple(
            TankSignals(
                tank.id,
                dispense=levels[tank.dispense.pin] == tank.dispense.active_level,
                refill=levels[tank.refill.pin] == tank.refill.active_level,
            )
            for tank in self._tanks
        )
