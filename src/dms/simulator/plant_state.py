from dms.domain.events import EventKind
from dms.simulator.layout import Input, MeterDevice
from dms.simulator.scenario_model import ScenarioData

UNASSIGNED_PIN_LEVEL = 1


def silo_mass_kg(scenario: ScenarioData, silo_id: int, t_ns: int) -> float:
    mass_kg = float(scenario.start_mass_kg(silo_id))
    for event in scenario.events:
        if scenario.layout.silo_of(event.tank_id).id == silo_id:
            mass_kg += event.sign * event.mass_kg * event.profile.fraction(event.progress(t_ns))
    return mass_kg


def indication_kg(mass_kg: float, meter: MeterDevice) -> int:
    return round(mass_kg / meter.division_kg) * meter.division_kg


def signal_active(scenario: ScenarioData, tank_id: int, kind: EventKind, t_ns: int) -> bool:
    return any(
        event.tank_id == tank_id and event.kind == kind and event.start_ns <= t_ns < event.end_ns
        for event in scenario.events
    )


def pin_levels(scenario: ScenarioData, t_ns: int) -> tuple[tuple[int, int], ...]:
    levels = {pin: UNASSIGNED_PIN_LEVEL for pin in scenario.layout.board.pins}
    for silo in scenario.layout.silos:
        for tank in silo.tanks:
            signals: tuple[tuple[EventKind, Input], ...] = (
                (EventKind.DISPENSE, tank.dispense),
                (EventKind.REFILL, tank.refill),
            )
            for kind, wiring in signals:
                active = signal_active(scenario, tank.id, kind, t_ns)
                levels[wiring.pin] = wiring.active_level if active else 1 - wiring.active_level
    return tuple(levels.items())
