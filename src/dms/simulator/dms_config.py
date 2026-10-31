from pathlib import Path

import tomli_w

from dms.config.models import (
    AcquisitionConfig,
    BoardConfig,
    InputConfig,
    MeanRateConfig,
    MeterConfig,
    SiloConfig,
    TankConfig,
    TemperatureSensorConfig,
)
from dms.simulator.encoders import BOARD_FRAME_END
from dms.simulator.layout import Input, PlantLayout

DEFAULT_RECONNECT_DELAY_S = 5.0
DEFAULT_SILENCE_TIMEOUT_S = 5.0
SCENARIO_MEAN_RATE_N = 3


def acquisition_config(
    layout: PlantLayout,
    link_dir: Path,
    reconnect_delay_s: float = DEFAULT_RECONNECT_DELAY_S,
    silence_timeout_s: float = DEFAULT_SILENCE_TIMEOUT_S,
) -> AcquisitionConfig:
    meters = tuple(
        MeterConfig(
            id=silo.meter_id,
            port=str((link_dir / silo.meter_id).absolute()),
            baudrate=silo.meter.baudrate,
            format=silo.meter.format,
            frame_end=silo.meter.frame_end,
            reconnect_delay_s=reconnect_delay_s,
            silence_timeout_s=silence_timeout_s,
        )
        for silo in layout.silos
    )
    silos = tuple(
        SiloConfig(id=silo.id, name=silo.display_name, meter_id=silo.meter_id)
        for silo in layout.silos
    )
    board = BoardConfig(
        id=layout.board.id,
        port=str((link_dir / layout.board.id).absolute()),
        baudrate=layout.board.baudrate,
        frame_end=BOARD_FRAME_END.decode("ascii"),
        reconnect_delay_s=reconnect_delay_s,
        silence_timeout_s=silence_timeout_s,
    )
    tanks = tuple(
        TankConfig(
            id=tank.id,
            name=tank.display_name,
            silo_id=silo.id,
            dispense=_input_config(tank.dispense),
            refill=_input_config(tank.refill),
        )
        for silo in layout.silos
        for tank in silo.tanks
    )
    temperature_sensors = tuple(
        TemperatureSensorConfig(
            id=sensor.id,
            name=sensor.display_name,
            address=sensor.address,
            silo_id=sensor.silo_id,
            leg=sensor.leg,
        )
        for sensor in layout.board.sensors
        if sensor.configured
    )
    return AcquisitionConfig(
        meters=meters,
        silos=silos,
        board=board,
        tanks=tanks,
        temperature_sensors=temperature_sensors,
        estimation_methods=(MeanRateConfig(n=SCENARIO_MEAN_RATE_N),),
    )


def _input_config(signal: Input) -> InputConfig:
    return InputConfig(pin=signal.pin, active_level=signal.active_level)


def render_acquisition_toml(config: AcquisitionConfig) -> str:
    return tomli_w.dumps(config.model_dump(mode="json", exclude_none=True))
