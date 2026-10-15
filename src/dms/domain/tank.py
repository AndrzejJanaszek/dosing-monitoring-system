from dataclasses import dataclass
from typing import Literal

from dms.messages import TankSignals

type SignalKind = Literal["dispense", "refill"]


@dataclass(frozen=True, slots=True)
class SignalChange:
    tank_id: int
    signal: SignalKind
    active: bool
    previous: bool | None


class Tank:
    def __init__(self, tank_id: int) -> None:
        self.tank_id = tank_id
        self._dispense: bool | None = None
        self._refill: bool | None = None

    def on_signals(self, signals: TankSignals) -> list[SignalChange]:
        changes: list[SignalChange] = []
        if signals.dispense != self._dispense:
            changes.append(SignalChange(self.tank_id, "dispense", signals.dispense, self._dispense))
            self._dispense = signals.dispense
        if signals.refill != self._refill:
            changes.append(SignalChange(self.tank_id, "refill", signals.refill, self._refill))
            self._refill = signals.refill
        return changes
