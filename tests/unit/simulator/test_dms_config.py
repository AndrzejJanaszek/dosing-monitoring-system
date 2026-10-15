from pathlib import Path

import pytest

from dms.config.loader import load_acquisition
from dms.simulator.catalog import TWO_SILOS
from dms.simulator.dms_config import acquisition_config, render_acquisition_toml
from dms.simulator.layout import MeterDevice, PlantLayout, SiloLayout
from tests.unit.simulator.builders import tank


def test_meters_and_silos_follow_the_layout() -> None:
    config = acquisition_config(TWO_SILOS, Path("/tmp/ports"))

    assert [meter.id for meter in config.meters] == ["meter-1", "meter-2"]
    assert [meter.port for meter in config.meters] == ["/tmp/ports/meter-1", "/tmp/ports/meter-2"]
    assert [(silo.id, silo.name, silo.meter_id) for silo in config.silos] == [
        (1, "Silos 1", "meter-1"),
        (2, "Silos 2", "meter-2"),
    ]


def test_relative_link_dir_gives_absolute_ports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    config = acquisition_config(TWO_SILOS, Path("ports"))

    assert config.meters[0].port == str(tmp_path / "ports" / "meter-1")


def test_meter_settings_come_from_the_layout() -> None:
    meter = MeterDevice(baudrate=19200, frame_end="\n")
    layout = PlantLayout((SiloLayout(1, (tank(1, 4, 5),), meter),))

    config = acquisition_config(layout, Path("/tmp/ports"), reconnect_delay_s=1.0)

    assert config.meters[0].baudrate == 19200
    assert config.meters[0].frame_end == "\n"
    assert config.meters[0].reconnect_delay_s == 1.0


def test_rendered_toml_loads_back_to_the_same_config(tmp_path: Path) -> None:
    config = acquisition_config(TWO_SILOS, tmp_path / "ports")
    (tmp_path / "acquisition.toml").write_text(render_acquisition_toml(config), encoding="utf-8")

    assert load_acquisition(tmp_path) == config
