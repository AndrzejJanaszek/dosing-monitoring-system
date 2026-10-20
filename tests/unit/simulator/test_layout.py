from collections.abc import Callable

import pytest

from dms.simulator.errors import ScenarioError
from dms.simulator.layout import (
    ErrorCode,
    FixedValue,
    Input,
    MeterDevice,
    Missing,
    PlantLayout,
    SensorFault,
    SignalBoard,
    SiloLayout,
    TemperatureSensor,
)
from tests.unit.simulator.builders import one_tank_layout, tank, two_tank_layout

THREE_TANKS = (tank(1, 4, 5), tank(2, 6, 7), tank(3, 8, 9))


def test_valid_layout_exposes_lookups() -> None:
    layout = two_tank_layout()

    assert layout.tank(2).dispense.pin == 6
    assert layout.silo_of(2).id == 1
    assert layout.silo_of_meter("meter-1").id == 1
    assert layout.device_ids() == ("meter-1", "arduino")


def test_silo_names_and_meter_ids() -> None:
    assert SiloLayout(id=3, tanks=(tank(1, 4, 5),)).display_name == "Silos 3"
    assert SiloLayout(id=3, tanks=(tank(1, 4, 5),), name="Cement").display_name == "Cement"
    assert SiloLayout(id=3, tanks=(tank(1, 4, 5),)).meter_id == "meter-3"


def sensor_with_faults(*faults: SensorFault) -> PlantLayout:
    sensor = TemperatureSensor(id=1, address="28A8F126AB240B1C", start_c=20.0, faults=faults)
    return PlantLayout(one_tank_layout().silos, SignalBoard(sensors=(sensor,)))


INVALID_LAYOUTS: dict[str, tuple[Callable[[], object], str]] = {
    "duplicate-silo-id": (
        lambda: PlantLayout(
            (SiloLayout(id=1, tanks=(tank(1, 4, 5),)), SiloLayout(id=1, tanks=(tank(2, 6, 7),)))
        ),
        "silos[1].id: duplicate silo id 1",
    ),
    "duplicate-tank-id": (
        lambda: PlantLayout(
            (SiloLayout(id=1, tanks=(tank(1, 4, 5),)), SiloLayout(id=2, tanks=(tank(1, 6, 7),)))
        ),
        "silos[1].tanks[0].id: duplicate tank id 1",
    ),
    "silo-without-tanks": (
        lambda: PlantLayout((SiloLayout(id=1, tanks=()),)),
        "silos[0].tanks: 0 tanks",
    ),
    "silo-with-too-many-tanks": (
        lambda: PlantLayout((SiloLayout(id=1, tanks=THREE_TANKS),)),
        "silos[0].tanks: 3 tanks",
    ),
    "pin-used-twice": (
        lambda: PlantLayout((SiloLayout(id=1, tanks=(tank(1, 4, 4),)),)),
        "silos[0].tanks[0].refill.pin: pin 4 is already used",
    ),
    "pin-not-on-board": (
        lambda: PlantLayout((SiloLayout(id=1, tanks=(tank(1, 4, 12),)),)),
        "silos[0].tanks[0].refill.pin: pin 12 is not on board",
    ),
    "active-level-out-of-range": (
        lambda: PlantLayout((SiloLayout(id=1, tanks=(tank(1, 4, 5, active_level=2),)),)),
        "active_level: 2 is not 0 or 1",
    ),
    "duplicate-board-pin": (
        lambda: PlantLayout(
            (SiloLayout(id=1, tanks=(tank(1, 4, 5),)),), SignalBoard(pins=(4, 5, 5))
        ),
        "board.pins: duplicate pin 5",
    ),
    "sensor-address-malformed": (
        lambda: PlantLayout(
            one_tank_layout().silos,
            SignalBoard(sensors=(TemperatureSensor(id=1, address="28a8", start_c=20.0),)),
        ),
        "board.sensors[0].address",
    ),
    "duplicate-sensor-address": (
        lambda: PlantLayout(
            one_tank_layout().silos,
            SignalBoard(
                sensors=(
                    TemperatureSensor(id=1, address="28A8F126AB240B1C", start_c=20.0),
                    TemperatureSensor(id=2, address="28A8F126AB240B1C", start_c=21.0),
                )
            ),
        ),
        "board.sensors[1].address: duplicate",
    ),
    "duplicate-sensor-id": (
        lambda: PlantLayout(
            one_tank_layout().silos,
            SignalBoard(
                sensors=(
                    TemperatureSensor(id=1, address="28A8F126AB240B1C", start_c=20.0),
                    TemperatureSensor(id=1, address="28FF4A7C61160398", start_c=21.0),
                )
            ),
        ),
        "board.sensors[1].id: duplicate sensor id 1",
    ),
    "sensor-id-out-of-range": (
        lambda: PlantLayout(
            one_tank_layout().silos,
            SignalBoard(
                sensors=(TemperatureSensor(id=0, address="28A8F126AB240B1C", start_c=20.0),)
            ),
        ),
        "board.sensors[0].id: 0 is outside",
    ),
    "sensor-in-unknown-silo": (
        lambda: PlantLayout(
            one_tank_layout().silos,
            SignalBoard(
                sensors=(
                    TemperatureSensor(id=1, address="28A8F126AB240B1C", start_c=20.0, silo_id=9),
                )
            ),
        ),
        "board.sensors[0].silo_id: unknown silo 9",
    ),
    "sensor-leg-without-silo": (
        lambda: PlantLayout(
            one_tank_layout().silos,
            SignalBoard(
                sensors=(TemperatureSensor(id=1, address="28A8F126AB240B1C", start_c=20.0, leg=1),)
            ),
        ),
        "board.sensors[0].leg: leg requires a silo_id",
    ),
    "sensor-leg-below-range": (
        lambda: PlantLayout(
            one_tank_layout().silos,
            SignalBoard(
                sensors=(
                    TemperatureSensor(
                        id=1, address="28A8F126AB240B1C", start_c=20.0, silo_id=1, leg=0
                    ),
                )
            ),
        ),
        "board.sensors[0].leg: 0 is outside 1..32767",
    ),
    "sensor-leg-above-range": (
        lambda: PlantLayout(
            one_tank_layout().silos,
            SignalBoard(
                sensors=(
                    TemperatureSensor(
                        id=1, address="28A8F126AB240B1C", start_c=20.0, silo_id=1, leg=32768
                    ),
                )
            ),
        ),
        "board.sensors[0].leg: 32768 is outside 1..32767",
    ),
    "fault-ends-before-it-starts": (
        lambda: sensor_with_faults(SensorFault(start_s=5.0, end_s=5.0, kind=Missing())),
        "board.sensors[0].faults[0]: end must be after",
    ),
    "fault-starts-before-zero": (
        lambda: sensor_with_faults(SensorFault(start_s=-1.0, end_s=5.0, kind=Missing())),
        "board.sensors[0].faults[0]: end must be after",
    ),
    "fault-with-empty-error-code": (
        lambda: sensor_with_faults(SensorFault(start_s=1.0, end_s=5.0, kind=ErrorCode(""))),
        "board.sensors[0].faults[0].kind: error code is empty",
    ),
    "overlapping-faults": (
        lambda: sensor_with_faults(
            SensorFault(start_s=1.0, end_s=5.0, kind=Missing()),
            SensorFault(start_s=4.0, end_s=8.0, kind=FixedValue(85.0)),
        ),
        "board.sensors[0].faults[1]: overlaps another fault",
    ),
    "silo-id-out-of-range": (
        lambda: PlantLayout((SiloLayout(id=0, tanks=(tank(1, 4, 5),)),)),
        "silos[0].id: 0 is outside",
    ),
    "tank-id-out-of-range": (
        lambda: PlantLayout((SiloLayout(id=1, tanks=(tank(40000, 4, 5),)),)),
        "silos[0].tanks[0].id: 40000 is outside",
    ),
    "meter-rate-zero": (
        lambda: PlantLayout(
            (SiloLayout(id=1, tanks=(tank(1, 4, 5),), meter=MeterDevice(rate_hz=0)),)
        ),
        "meter.rate_hz",
    ),
    "meter-rate-too-high": (
        lambda: PlantLayout(
            (SiloLayout(id=1, tanks=(tank(1, 4, 5),), meter=MeterDevice(rate_hz=1e10)),)
        ),
        "meter.rate_hz: 1e+10 is outside",
    ),
    "negative-division": (
        lambda: PlantLayout(
            (SiloLayout(id=1, tanks=(tank(1, 4, 5),), meter=MeterDevice(division_kg=-1)),)
        ),
        "meter.division_kg",
    ),
    "pins-period-zero": (
        lambda: PlantLayout(one_tank_layout().silos, SignalBoard(pins_period_s=0)),
        "board.pins_period_s",
    ),
    "temperatures-period-too-short": (
        lambda: PlantLayout(one_tank_layout().silos, SignalBoard(temperatures_period_s=1e-10)),
        "board.temperatures_period_s: 1e-10 s is shorter than",
    ),
    "board-id-equals-meter-id": (
        lambda: PlantLayout(one_tank_layout().silos, SignalBoard(id="meter-1")),
        "board.id: 'meter-1' is also a meter id",
    ),
}


@pytest.mark.parametrize("rule", INVALID_LAYOUTS)
def test_invalid_layout_is_rejected(rule: str) -> None:
    build, expected_fragment = INVALID_LAYOUTS[rule]

    with pytest.raises(ScenarioError) as raised:
        build()

    assert any(expected_fragment in error for error in raised.value.errors), raised.value.errors


def test_several_layout_errors_are_reported_together() -> None:
    with pytest.raises(ScenarioError) as raised:
        PlantLayout((SiloLayout(id=1, tanks=(tank(1, 4, 12, active_level=2),)),))

    assert len(raised.value.errors) == 3


def test_input_defaults_to_active_low() -> None:
    assert Input(4).active_level == 0
