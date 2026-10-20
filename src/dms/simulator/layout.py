import re
from collections import Counter
from dataclasses import dataclass, field

from dms.config.models import (
    MAX_SMALLINT,
    MAX_TANKS_PER_SILO,
    PIN_LEVELS,
    BaudRate,
    MeterFormat,
)
from dms.domain.events import EventKind
from dms.simulator.errors import ScenarioError

DEFAULT_METER_RATE_HZ = 10.0
DEFAULT_DIVISION_KG = 20
DEFAULT_BAUDRATE: BaudRate = 9600
DEFAULT_METER_FRAME_END = "\r\n"
DEFAULT_BOARD_ID = "arduino"
DEFAULT_BOARD_PINS = (4, 5, 6, 7, 8, 9)
DEFAULT_PINS_PERIOD_S = 0.25
DEFAULT_TEMPERATURES_PERIOD_S = 1.0
DEFAULT_ACTIVE_LEVEL = 0
MIN_DEVICE_PERIOD_S = 0.001
MAX_METER_RATE_HZ = 1 / MIN_DEVICE_PERIOD_S
MIN_ID = 1
MIN_TANKS_PER_SILO = 1
SENSOR_ADDRESS_PATTERN = re.compile(r"^[0-9A-F]{16}$")


@dataclass(frozen=True, slots=True, kw_only=True)
class MeterDevice:
    format: MeterFormat = MeterFormat.DGTP
    rate_hz: float = DEFAULT_METER_RATE_HZ
    division_kg: int = DEFAULT_DIVISION_KG
    baudrate: BaudRate = DEFAULT_BAUDRATE
    frame_end: str = DEFAULT_METER_FRAME_END


@dataclass(frozen=True, slots=True)
class Input:
    pin: int
    active_level: int = DEFAULT_ACTIVE_LEVEL


@dataclass(frozen=True, slots=True, kw_only=True)
class TankWiring:
    id: int
    dispense: Input
    refill: Input
    name: str | None = None

    @property
    def display_name(self) -> str:
        return self.name if self.name is not None else f"Zbiornik {self.id}"


@dataclass(frozen=True, slots=True, kw_only=True)
class SiloLayout:
    id: int
    tanks: tuple[TankWiring, ...]
    meter: MeterDevice = MeterDevice()
    name: str | None = None

    @property
    def meter_id(self) -> str:
        return f"meter-{self.id}"

    @property
    def display_name(self) -> str:
        return self.name if self.name is not None else f"Silos {self.id}"


@dataclass(frozen=True, slots=True)
class TemperatureSensor:
    address: str
    temperature_c: float


@dataclass(frozen=True, slots=True, kw_only=True)
class SignalBoard:
    id: str = DEFAULT_BOARD_ID
    pins: tuple[int, ...] = DEFAULT_BOARD_PINS
    pins_period_s: float = DEFAULT_PINS_PERIOD_S
    temperatures_period_s: float = DEFAULT_TEMPERATURES_PERIOD_S
    sensors: tuple[TemperatureSensor, ...] = ()
    baudrate: BaudRate = DEFAULT_BAUDRATE
    banner: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class PlantLayout:
    silos: tuple[SiloLayout, ...]
    board: SignalBoard = field(default_factory=SignalBoard)

    def __post_init__(self) -> None:
        errors = layout_errors(self)
        if errors:
            raise ScenarioError(errors)

    def tank(self, tank_id: int) -> TankWiring:
        return next(tank for silo in self.silos for tank in silo.tanks if tank.id == tank_id)

    def silo_of(self, tank_id: int) -> SiloLayout:
        return next(silo for silo in self.silos for tank in silo.tanks if tank.id == tank_id)

    def silo_of_meter(self, meter_id: str) -> SiloLayout:
        return next(silo for silo in self.silos if silo.meter_id == meter_id)

    def device_ids(self) -> tuple[str, ...]:
        return (*(silo.meter_id for silo in self.silos), self.board.id)


def layout_errors(layout: PlantLayout) -> list[str]:
    return [
        *_silo_errors(layout),
        *_tank_errors(layout),
        *_input_errors(layout),
        *_board_errors(layout.board),
        *_meter_errors(layout),
        *_device_id_errors(layout),
    ]


def _silo_errors(layout: PlantLayout) -> list[str]:
    errors: list[str] = []
    seen: set[int] = set()
    for index, silo in enumerate(layout.silos):
        if silo.id in seen:
            errors.append(f"silos[{index}].id: duplicate silo id {silo.id}")
        seen.add(silo.id)

        if not MIN_ID <= silo.id <= MAX_SMALLINT:
            errors.append(f"silos[{index}].id: {silo.id} is outside {MIN_ID}..{MAX_SMALLINT}")

        if not MIN_TANKS_PER_SILO <= len(silo.tanks) <= MAX_TANKS_PER_SILO:
            errors.append(
                f"silos[{index}].tanks: {len(silo.tanks)} tanks,"
                f" expected {MIN_TANKS_PER_SILO}..{MAX_TANKS_PER_SILO}"
            )
    return errors


def _tank_errors(layout: PlantLayout) -> list[str]:
    errors: list[str] = []
    seen: set[int] = set()
    for silo_index, silo in enumerate(layout.silos):
        for tank_index, tank in enumerate(silo.tanks):
            path = f"silos[{silo_index}].tanks[{tank_index}].id"
            if tank.id in seen:
                errors.append(f"{path}: duplicate tank id {tank.id}")
            seen.add(tank.id)

            if not MIN_ID <= tank.id <= MAX_SMALLINT:
                errors.append(f"{path}: {tank.id} is outside {MIN_ID}..{MAX_SMALLINT}")
    return errors


def _input_errors(layout: PlantLayout) -> list[str]:
    errors: list[str] = []
    used_pins: dict[int, str] = {}
    for silo_index, silo in enumerate(layout.silos):
        for tank_index, tank in enumerate(silo.tanks):
            for name, signal in (
                (EventKind.DISPENSE, tank.dispense),
                (EventKind.REFILL, tank.refill),
            ):
                path = f"silos[{silo_index}].tanks[{tank_index}].{name}"

                if signal.pin in used_pins:
                    errors.append(
                        f"{path}.pin: pin {signal.pin} is already used by {used_pins[signal.pin]}"
                    )
                used_pins.setdefault(signal.pin, path)

                if signal.pin not in layout.board.pins:
                    errors.append(
                        f"{path}.pin: pin {signal.pin} is not on board '{layout.board.id}'"
                    )

                if signal.active_level not in PIN_LEVELS:
                    errors.append(f"{path}.active_level: {signal.active_level} is not 0 or 1")
    return errors


def _board_errors(board: SignalBoard) -> list[str]:
    errors = [
        f"board.pins: duplicate pin {pin}"
        for pin, count in Counter(board.pins).items()
        if count > 1
    ]

    seen: set[str] = set()
    for index, sensor in enumerate(board.sensors):
        if SENSOR_ADDRESS_PATTERN.match(sensor.address) is None:
            errors.append(
                f"board.sensors[{index}].address: '{sensor.address}' is not 16 hex digits"
            )

        if sensor.address in seen:
            errors.append(f"board.sensors[{index}].address: duplicate address '{sensor.address}'")
        seen.add(sensor.address)

    errors.extend(
        f"board.{name}: {value:g} s is shorter than {MIN_DEVICE_PERIOD_S:g} s"
        for name, value in (
            ("pins_period_s", board.pins_period_s),
            ("temperatures_period_s", board.temperatures_period_s),
        )
        if value < MIN_DEVICE_PERIOD_S
    )
    return errors


def _meter_errors(layout: PlantLayout) -> list[str]:
    errors: list[str] = []
    for index, silo in enumerate(layout.silos):
        if not 0 < silo.meter.rate_hz <= MAX_METER_RATE_HZ:
            errors.append(
                f"silos[{index}].meter.rate_hz: {silo.meter.rate_hz:g}"
                f" is outside 0..{MAX_METER_RATE_HZ:g} Hz"
            )

        if silo.meter.division_kg <= 0:
            errors.append(
                f"silos[{index}].meter.division_kg: {silo.meter.division_kg} must be positive"
            )
    return errors


def _device_id_errors(layout: PlantLayout) -> list[str]:
    return [
        f"board.id: '{device_id}' is also a meter id"
        for device_id, count in Counter(layout.device_ids()).items()
        if count > 1
    ]
