from pathlib import Path

import tomli_w

from dms.config.models import AcquisitionConfig, MeterConfig, SiloConfig
from dms.simulator.layout import PlantLayout

DEFAULT_RECONNECT_DELAY_S = 5.0
DEFAULT_SILENCE_TIMEOUT_S = 5.0


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
    return AcquisitionConfig(meters=meters, silos=silos)


def render_acquisition_toml(config: AcquisitionConfig) -> str:
    return tomli_w.dumps(config.model_dump(mode="json"))
