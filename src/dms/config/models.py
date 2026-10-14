from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from dms.logs.setup import LogFormat, LogLevel

MAX_SMALLINT = 32767
MIN_PORT = 1
MAX_PORT = 65535
DEFAULT_DATABASE_HOST = "/var/run/postgresql"
DEFAULT_DATABASE_PORT = 5432
DEFAULT_DATABASE_NAME = "dms"
DEFAULT_TICK_INTERVAL_S = 1.0
DEFAULT_MAX_READING_AGE_S = 1.0
NON_EMPTY = 1
DEFAULT_METER_MAX_FRAME_LENGTH = 64
DEFAULT_BOARD_MAX_FRAME_LENGTH = 512
MAX_TANKS_PER_SILO = 2

type BaudRate = Literal[300, 600, 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]
type MeterFormat = Literal["dgtp"]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DatabaseConfig(FrozenModel):
    host: str = DEFAULT_DATABASE_HOST
    port: int = Field(default=DEFAULT_DATABASE_PORT, ge=MIN_PORT, le=MAX_PORT)
    dbname: str = Field(default=DEFAULT_DATABASE_NAME, min_length=NON_EMPTY)


class LoggingConfig(FrozenModel):
    level: LogLevel = "INFO"
    format: LogFormat = "auto"


class SharedConfig(FrozenModel):
    database: DatabaseConfig = DatabaseConfig()
    logging: LoggingConfig = LoggingConfig()


class EngineConfig(FrozenModel):
    tick_interval_s: float = Field(default=DEFAULT_TICK_INTERVAL_S, gt=0)
    max_reading_age_s: float = Field(default=DEFAULT_MAX_READING_AGE_S, gt=0)


class SerialPortConfig(FrozenModel):
    id: str = Field(min_length=NON_EMPTY)
    port: str = Field(min_length=NON_EMPTY)
    baudrate: BaudRate
    frame_start: str = ""
    frame_end: str = Field(min_length=NON_EMPTY)
    reconnect_delay_s: float = Field(gt=0)
    silence_timeout_s: float = Field(gt=0)


class MeterConfig(SerialPortConfig):
    format: MeterFormat
    max_frame_length: int = Field(default=DEFAULT_METER_MAX_FRAME_LENGTH, gt=0)


class BoardConfig(SerialPortConfig):
    max_frame_length: int = Field(default=DEFAULT_BOARD_MAX_FRAME_LENGTH, gt=0)


class InputConfig(FrozenModel):
    pin: StrictInt = Field(ge=0)
    active_level: StrictInt = Field(ge=0, le=1)


class TankConfig(FrozenModel):
    id: int = Field(ge=NON_EMPTY, le=MAX_SMALLINT)
    name: str = Field(min_length=NON_EMPTY)
    silo_id: int = Field(ge=NON_EMPTY, le=MAX_SMALLINT)
    dispense: InputConfig
    refill: InputConfig


class SiloConfig(FrozenModel):
    id: int = Field(ge=NON_EMPTY, le=MAX_SMALLINT)
    name: str = Field(min_length=NON_EMPTY)
    meter_id: str = Field(min_length=NON_EMPTY)


class AcquisitionConfig(FrozenModel):
    engine: EngineConfig = EngineConfig()
    meters: tuple[MeterConfig, ...]
    silos: tuple[SiloConfig, ...]
    board: BoardConfig | None = None
    tanks: tuple[TankConfig, ...] = ()


def validate_acquisition_rules(config: AcquisitionConfig) -> list[str]:
    errors: list[str] = []
    errors.extend(_duplicates("meters", "id", [meter.id for meter in config.meters]))
    errors.extend(_meter_and_board_errors(config))
    errors.extend(_duplicates("silos", "id", [silo.id for silo in config.silos]))
    errors.extend(_silo_errors(config))
    errors.extend(_tank_errors(config))
    return errors


def _meter_and_board_errors(config: AcquisitionConfig) -> list[str]:
    errors = _duplicates("meters", "port", [meter.port for meter in config.meters])
    board = config.board
    if board is None:
        return errors
    if board.id in {meter.id for meter in config.meters}:
        errors.append(f"board.id: duplicate id '{board.id}'")
    if board.port in {meter.port for meter in config.meters}:
        errors.append(f"board.port: duplicate port '{board.port}'")
    return errors


def _silo_errors(config: AcquisitionConfig) -> list[str]:
    errors: list[str] = []
    meter_ids = {meter.id for meter in config.meters}
    silo_by_meter: dict[str, int] = {}
    for index, silo in enumerate(config.silos):
        if silo.meter_id not in meter_ids:
            errors.append(f"silos[{index}].meter_id: unknown meter '{silo.meter_id}'")
        elif silo.meter_id in silo_by_meter:
            errors.append(
                f"silos[{index}].meter_id: meter '{silo.meter_id}' is already assigned"
                f" to silo {silo_by_meter[silo.meter_id]}"
            )
        else:
            silo_by_meter[silo.meter_id] = silo.id
    return errors


def _tank_errors(config: AcquisitionConfig) -> list[str]:
    errors = _duplicates("tanks", "id", [tank.id for tank in config.tanks])
    if config.tanks and config.board is None:
        errors.append("tanks: tanks require a [board] section")

    silo_ids = {silo.id for silo in config.silos}
    tanks_in_silo: Counter[int] = Counter()
    pin_owners: dict[int, str] = {}
    for index, tank in enumerate(config.tanks):
        if tank.silo_id not in silo_ids:
            errors.append(f"tanks[{index}].silo_id: unknown silo {tank.silo_id}")
        tanks_in_silo[tank.silo_id] += 1
        if tanks_in_silo[tank.silo_id] > MAX_TANKS_PER_SILO:
            errors.append(
                f"tanks[{index}].silo_id: silo {tank.silo_id} has more than"
                f" {MAX_TANKS_PER_SILO} tanks"
            )
        for signal, input_config in (("dispense", tank.dispense), ("refill", tank.refill)):
            owner = pin_owners.get(input_config.pin)
            if owner is not None:
                errors.append(
                    f"tanks[{index}].{signal}.pin: pin {input_config.pin}"
                    f" is already assigned to {owner}"
                )
            else:
                pin_owners[input_config.pin] = f"tanks[{index}].{signal}"
    return errors


def _duplicates[T](collection: str, field: str, values: list[T]) -> list[str]:
    first_seen: set[T] = set()
    errors: list[str] = []
    for index, value in enumerate(values):
        if value in first_seen:
            errors.append(f"{collection}[{index}].{field}: duplicate {field} '{value}'")
        first_seen.add(value)
    return errors
