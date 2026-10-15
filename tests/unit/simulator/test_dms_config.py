from pathlib import Path

import pytest

from dms.config.loader import load_acquisition
from dms.config.models import BoardConfig, validate_acquisition_rules
from dms.simulator.catalog import TWO_SILOS, TWO_TANKS
from dms.simulator.dms_config import acquisition_config, render_acquisition_toml
from dms.simulator.layout import MeterDevice, PlantLayout, SiloLayout, TankWiring
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


def test_board_and_tanks_follow_the_layout() -> None:
    config = acquisition_config(TWO_TANKS, Path("/tmp/ports"))

    assert config.board is not None
    assert (config.board.id, config.board.port) == ("arduino", "/tmp/ports/arduino")
    assert config.board.frame_end == "\r\n"
    assert [
        (tank.id, tank.name, tank.silo_id, tank.dispense.pin, tank.refill.pin)
        for tank in config.tanks
    ] == [(1, "Zbiornik 1", 1, 4, 5), (2, "Zbiornik 2", 1, 6, 7)]


def test_tank_name_comes_from_the_layout() -> None:
    wiring = TankWiring(1, tank(1, 4, 5).dispense, tank(1, 4, 5).refill, name="Piasek")
    layout = PlantLayout((SiloLayout(1, (wiring,)),))

    assert acquisition_config(layout, Path("/tmp/ports")).tanks[0].name == "Piasek"


def test_generated_configuration_follows_all_rules() -> None:
    assert validate_acquisition_rules(acquisition_config(TWO_TANKS, Path("/tmp/ports"))) == []


def test_tanks_of_the_first_silo_come_before_tanks_of_the_next() -> None:
    config = acquisition_config(TWO_SILOS, Path("/tmp/ports"))

    assert [(tank.id, tank.silo_id) for tank in config.tanks] == [(1, 1), (2, 2)]


def mutated(**changes: object) -> list[str]:
    config = acquisition_config(TWO_TANKS, Path("/tmp/ports"))
    return validate_acquisition_rules(config.model_copy(update=changes))


def test_board_on_a_meter_port_breaks_the_rules() -> None:
    config = acquisition_config(TWO_TANKS, Path("/tmp/ports"))
    board = config.board
    assert board is not None

    errors = mutated(board=board.model_copy(update={"port": config.meters[0].port}))

    assert errors == [f"board.port: duplicate port '{config.meters[0].port}'"]


def test_board_with_a_meter_id_breaks_the_rules() -> None:
    config = acquisition_config(TWO_TANKS, Path("/tmp/ports"))
    board: BoardConfig | None = config.board
    assert board is not None

    assert mutated(board=board.model_copy(update={"id": "meter-1"})) == [
        "board.id: duplicate id 'meter-1'"
    ]


def test_repeated_tank_id_breaks_the_rules() -> None:
    config = acquisition_config(TWO_TANKS, Path("/tmp/ports"))
    second = config.tanks[1].model_copy(update={"id": 1})

    assert mutated(tanks=(config.tanks[0], second)) == ["tanks[1].id: duplicate id '1'"]


def test_tank_in_unknown_silo_breaks_the_rules() -> None:
    config = acquisition_config(TWO_TANKS, Path("/tmp/ports"))
    moved = config.tanks[1].model_copy(update={"silo_id": 9})

    assert mutated(tanks=(config.tanks[0], moved)) == ["tanks[1].silo_id: unknown silo 9"]


def test_third_tank_in_a_silo_breaks_the_rules() -> None:
    config = acquisition_config(TWO_TANKS, Path("/tmp/ports"))
    third = config.tanks[1].model_copy(update={"id": 3})

    assert mutated(tanks=(*config.tanks, third))[0] == (
        "tanks[2].silo_id: silo 1 has more than 2 tanks"
    )


def test_tanks_without_board_break_the_rules() -> None:
    assert mutated(board=None) == ["tanks: tanks require a [board] section"]


def test_pin_shared_by_two_tanks_breaks_the_rules() -> None:
    config = acquisition_config(TWO_TANKS, Path("/tmp/ports"))
    clashing = config.tanks[1].model_copy(update={"refill": config.tanks[0].dispense})

    assert mutated(tanks=(config.tanks[0], clashing)) == [
        "tanks[1].refill.pin: pin 4 is already assigned to tanks[0].dispense"
    ]
