from pathlib import Path

import pytest

from dms.config.loader import (
    CONFIG_DIR_VARIABLE,
    ConfigError,
    load_acquisition,
    load_shared,
    resolve_config_dir,
)

VALID_SHARED = """
[database]
host = "localhost"
port = 5433
dbname = "dms_x"

[logging]
level = "DEBUG"
format = "json"
"""

VALID_ACQUISITION = """
[engine]
tick_interval_s = 0.5
max_reading_age_s = 2.0

[[meters]]
id = "m1"
port = "/dev/ttyUSB0"
baudrate = 9600
format = "dgtp"
frame_start = ""
frame_end = "\\r\\n"
reconnect_delay_s = 5.0
silence_timeout_s = 5.0

[[meters]]
id = "m2"
port = "/dev/ttyUSB1"
baudrate = 9600
format = "dgtp"
frame_end = "\\r\\n"
reconnect_delay_s = 5.0
silence_timeout_s = 5.0

[[silos]]
id = 1
name = "Silos 1"
meter_id = "m1"
"""

METER_BLOCK = """
[[meters]]
id = "{id}"
port = "{port}"
baudrate = 9600
format = "dgtp"
frame_end = "\\r\\n"
reconnect_delay_s = 5.0
silence_timeout_s = 5.0
"""

SILO_BLOCK = """
[[silos]]
id = {id}
name = "Silos {id}"
meter_id = "{meter_id}"
"""


BOARD_BLOCK = """
[board]
id = "{id}"
port = "{port}"
baudrate = 9600
frame_end = "\\r\\n"
reconnect_delay_s = 5.0
silence_timeout_s = 5.0
"""

TANK_BLOCK = """
[[tanks]]
id = {id}
name = "Zbiornik {id}"
silo_id = {silo_id}
dispense = {{ pin = {dispense_pin}, active_level = {active_level} }}
refill = {{ pin = {refill_pin}, active_level = 0 }}
"""

SENSOR_BLOCK = """
[[temperature_sensors]]
id = {id}
name = "Czujnik {id}"
address = "{address}"
{extra}
"""

BASE_PLANT = (
    METER_BLOCK.format(id="m1", port="/a")
    + SILO_BLOCK.format(id=1, meter_id="m1")
    + BOARD_BLOCK.format(id="b1", port="/board")
)


def tank_block(
    tank_id: int = 1,
    silo_id: int = 1,
    dispense_pin: int = 4,
    refill_pin: int = 5,
    active_level: str = "0",
) -> str:
    return TANK_BLOCK.format(
        id=tank_id,
        silo_id=silo_id,
        dispense_pin=dispense_pin,
        refill_pin=refill_pin,
        active_level=active_level,
    )


def sensor_block(sensor_id: int = 1, address: str = "28A8F126AB240B1C", extra: str = "") -> str:
    return SENSOR_BLOCK.format(id=sensor_id, address=address, extra=extra)


def write(directory: Path, name: str, content: str) -> None:
    (directory / name).write_text(content, encoding="utf-8")


def errors_of(directory: Path) -> list[str]:
    with pytest.raises(ConfigError) as raised:
        load_acquisition(directory)
    return raised.value.errors


def test_valid_shared_config_is_loaded(tmp_path: Path) -> None:
    write(tmp_path, "shared.toml", VALID_SHARED)

    config = load_shared(tmp_path)

    assert config.database.host == "localhost"
    assert config.database.port == 5433
    assert config.logging.level == "DEBUG"
    assert config.logging.format == "json"


def test_empty_shared_config_uses_defaults(tmp_path: Path) -> None:
    write(tmp_path, "shared.toml", "")

    config = load_shared(tmp_path)

    assert config.database.host == "/var/run/postgresql"
    assert config.logging.format == "auto"


def test_valid_acquisition_config_is_loaded(tmp_path: Path) -> None:
    write(tmp_path, "acquisition.toml", VALID_ACQUISITION)

    config = load_acquisition(tmp_path)

    assert config.engine.tick_interval_s == 0.5
    assert [meter.id for meter in config.meters] == ["m1", "m2"]
    assert config.meters[0].frame_end == "\r\n"
    assert config.meters[1].frame_start == ""
    assert config.silos[0].meter_id == "m1"


def test_config_is_immutable(tmp_path: Path) -> None:
    write(tmp_path, "acquisition.toml", VALID_ACQUISITION)
    config = load_acquisition(tmp_path)

    with pytest.raises(ValueError, match="frozen"):
        config.engine.tick_interval_s = 3.0


def test_unknown_field_is_rejected_with_path(tmp_path: Path) -> None:
    write(tmp_path, "acquisition.toml", VALID_ACQUISITION + "\n[engine_typo]\nx = 1\n")

    assert errors_of(tmp_path) == ["acquisition.toml: engine_typo: Extra inputs are not permitted"]


def test_unknown_meter_in_silo_is_reported_with_path(tmp_path: Path) -> None:
    write(
        tmp_path,
        "acquisition.toml",
        METER_BLOCK.format(id="m1", port="/a") + SILO_BLOCK.format(id=1, meter_id="m3"),
    )

    assert errors_of(tmp_path) == ["acquisition.toml: silos[0].meter_id: unknown meter 'm3'"]


def test_duplicate_meter_id_and_port_are_reported(tmp_path: Path) -> None:
    content = METER_BLOCK.format(id="m1", port="/a") + METER_BLOCK.format(id="m1", port="/a")
    write(tmp_path, "acquisition.toml", content + SILO_BLOCK.format(id=1, meter_id="m1"))

    assert errors_of(tmp_path) == [
        "acquisition.toml: meters[1].id: duplicate id 'm1'",
        "acquisition.toml: meters[1].port: duplicate port '/a'",
    ]


def test_duplicate_silo_id_is_reported(tmp_path: Path) -> None:
    content = METER_BLOCK.format(id="m1", port="/a") + METER_BLOCK.format(id="m2", port="/b")
    content += SILO_BLOCK.format(id=1, meter_id="m1") + SILO_BLOCK.format(id=1, meter_id="m2")
    write(tmp_path, "acquisition.toml", content)

    assert errors_of(tmp_path) == ["acquisition.toml: silos[1].id: duplicate id '1'"]


def test_meter_assigned_to_two_silos_is_reported(tmp_path: Path) -> None:
    content = METER_BLOCK.format(id="m1", port="/a")
    content += SILO_BLOCK.format(id=1, meter_id="m1") + SILO_BLOCK.format(id=2, meter_id="m1")
    write(tmp_path, "acquisition.toml", content)

    assert errors_of(tmp_path) == [
        "acquisition.toml: silos[1].meter_id: meter 'm1' is already assigned to silo 1"
    ]


def test_empty_frame_end_is_rejected(tmp_path: Path) -> None:
    content = METER_BLOCK.format(id="m1", port="/a").replace('"\\r\\n"', '""')
    write(tmp_path, "acquisition.toml", content + SILO_BLOCK.format(id=1, meter_id="m1"))

    (error,) = errors_of(tmp_path)

    assert error.startswith("acquisition.toml: meters[0].frame_end:")


@pytest.mark.parametrize("field", ["reconnect_delay_s", "silence_timeout_s"])
def test_non_positive_time_is_rejected(tmp_path: Path, field: str) -> None:
    content = METER_BLOCK.format(id="m1", port="/a").replace(f"{field} = 5.0", f"{field} = 0")
    write(tmp_path, "acquisition.toml", content + SILO_BLOCK.format(id=1, meter_id="m1"))

    (error,) = errors_of(tmp_path)

    assert error.startswith(f"acquisition.toml: meters[0].{field}:")


@pytest.mark.parametrize("baudrate", [0, 96000, 9601])
def test_non_standard_baudrate_is_rejected(tmp_path: Path, baudrate: int) -> None:
    content = METER_BLOCK.format(id="m1", port="/a").replace(
        "baudrate = 9600", f"baudrate = {baudrate}"
    )
    write(tmp_path, "acquisition.toml", content + SILO_BLOCK.format(id=1, meter_id="m1"))

    (error,) = errors_of(tmp_path)

    assert error.startswith("acquisition.toml: meters[0].baudrate:")


def test_several_errors_are_reported_together(tmp_path: Path) -> None:
    content = METER_BLOCK.format(id="m1", port="/a").replace("baudrate = 9600", "baudrate = 0")
    content += SILO_BLOCK.format(id=0, meter_id="m1") + "\n[engine]\ntick_interval_s = -1\n"
    write(tmp_path, "acquisition.toml", content)

    errors = errors_of(tmp_path)

    assert len(errors) == 3
    assert any(".baudrate:" in error for error in errors)
    assert any("silos[0].id:" in error for error in errors)
    assert any("engine.tick_interval_s:" in error for error in errors)


def test_missing_file_is_a_readable_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as raised:
        load_shared(tmp_path)

    assert raised.value.errors == [f"shared.toml: file not found: {tmp_path / 'shared.toml'}"]


def test_invalid_toml_is_a_readable_error(tmp_path: Path) -> None:
    write(tmp_path, "shared.toml", "[database\nhost = ")

    with pytest.raises(ConfigError) as raised:
        load_shared(tmp_path)

    assert raised.value.errors[0].startswith("shared.toml: invalid TOML:")


def test_config_dir_comes_from_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(CONFIG_DIR_VARIABLE, str(tmp_path))
    write(tmp_path, "shared.toml", VALID_SHARED)

    assert resolve_config_dir() == tmp_path
    assert load_shared().database.dbname == "dms_x"


def test_config_dir_defaults_to_etc_dms(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CONFIG_DIR_VARIABLE, raising=False)

    assert resolve_config_dir() == Path("/etc/dms")


def test_board_and_tanks_are_loaded(tmp_path: Path) -> None:
    write(tmp_path, "acquisition.toml", BASE_PLANT + tank_block(1) + tank_block(2, 1, 6, 7, "1"))

    config = load_acquisition(tmp_path)

    assert config.board is not None
    assert config.board.id == "b1"
    assert config.board.max_frame_length == 512
    assert config.meters[0].max_frame_length == 64
    assert [
        (tank.id, tank.silo_id, tank.dispense.pin, tank.dispense.active_level)
        for tank in config.tanks
    ] == [
        (1, 1, 4, 0),
        (2, 1, 6, 1),
    ]


def test_configuration_without_board_and_tanks_is_valid(tmp_path: Path) -> None:
    write(tmp_path, "acquisition.toml", VALID_ACQUISITION)

    config = load_acquisition(tmp_path)

    assert config.board is None
    assert config.tanks == ()


def test_board_port_equal_to_meter_port_is_reported(tmp_path: Path) -> None:
    content = METER_BLOCK.format(id="m1", port="/a") + SILO_BLOCK.format(id=1, meter_id="m1")
    write(tmp_path, "acquisition.toml", content + BOARD_BLOCK.format(id="b1", port="/a"))

    assert errors_of(tmp_path) == ["acquisition.toml: board.port: duplicate port '/a'"]


def test_board_id_equal_to_meter_id_is_reported(tmp_path: Path) -> None:
    content = METER_BLOCK.format(id="m1", port="/a") + SILO_BLOCK.format(id=1, meter_id="m1")
    write(tmp_path, "acquisition.toml", content + BOARD_BLOCK.format(id="m1", port="/b"))

    assert errors_of(tmp_path) == ["acquisition.toml: board.id: duplicate id 'm1'"]


def test_duplicate_tank_id_is_reported(tmp_path: Path) -> None:
    write(tmp_path, "acquisition.toml", BASE_PLANT + tank_block(1) + tank_block(1, 1, 6, 7))

    assert errors_of(tmp_path) == ["acquisition.toml: tanks[1].id: duplicate id '1'"]


def test_tank_in_unknown_silo_is_reported(tmp_path: Path) -> None:
    write(tmp_path, "acquisition.toml", BASE_PLANT + tank_block(1, silo_id=9))

    assert errors_of(tmp_path) == ["acquisition.toml: tanks[0].silo_id: unknown silo 9"]


def test_third_tank_in_a_silo_is_reported(tmp_path: Path) -> None:
    content = BASE_PLANT + tank_block(1) + tank_block(2, 1, 6, 7) + tank_block(3, 1, 8, 9)
    write(tmp_path, "acquisition.toml", content)

    assert errors_of(tmp_path) == [
        "acquisition.toml: tanks[2].silo_id: silo 1 has more than 2 tanks"
    ]


def test_tanks_without_board_are_reported(tmp_path: Path) -> None:
    content = METER_BLOCK.format(id="m1", port="/a") + SILO_BLOCK.format(id=1, meter_id="m1")
    write(tmp_path, "acquisition.toml", content + tank_block(1))

    assert errors_of(tmp_path) == ["acquisition.toml: tanks: tanks require a [board] section"]


def test_pin_assigned_twice_is_reported_with_its_first_owner(tmp_path: Path) -> None:
    write(tmp_path, "acquisition.toml", BASE_PLANT + tank_block(1) + tank_block(2, 1, 6, 4))

    assert errors_of(tmp_path) == [
        "acquisition.toml: tanks[1].refill.pin: pin 4 is already assigned to tanks[0].dispense"
    ]


def test_dispense_and_refill_of_one_tank_cannot_share_a_pin(tmp_path: Path) -> None:
    write(tmp_path, "acquisition.toml", BASE_PLANT + tank_block(1, 1, 4, 4))

    assert errors_of(tmp_path) == [
        "acquisition.toml: tanks[0].refill.pin: pin 4 is already assigned to tanks[0].dispense"
    ]


def test_missing_active_level_is_reported_with_path(tmp_path: Path) -> None:
    content = BASE_PLANT + tank_block(1).replace(", active_level = 0 }", " }", 1)
    write(tmp_path, "acquisition.toml", content)

    (error,) = errors_of(tmp_path)

    assert error.startswith("acquisition.toml: tanks[0].dispense.active_level: Field required")


@pytest.mark.parametrize("active_level", ["2", "true", "false", "-1"])
def test_invalid_active_level_is_rejected(tmp_path: Path, active_level: str) -> None:
    write(tmp_path, "acquisition.toml", BASE_PLANT + tank_block(1, active_level=active_level))

    (error,) = errors_of(tmp_path)

    assert error.startswith("acquisition.toml: tanks[0].dispense.active_level:")


@pytest.mark.parametrize("pin", ["-1", "true"])
def test_invalid_pin_is_rejected(tmp_path: Path, pin: str) -> None:
    content = BASE_PLANT + tank_block(1).replace("pin = 4", f"pin = {pin}")
    write(tmp_path, "acquisition.toml", content)

    (error,) = errors_of(tmp_path)

    assert error.startswith("acquisition.toml: tanks[0].dispense.pin:")


def test_temperature_sensors_are_loaded_with_optional_silo_and_leg(tmp_path: Path) -> None:
    content = (
        BASE_PLANT
        + sensor_block(1, extra="silo_id = 1\nleg = 2")
        + sensor_block(2, "28FF4A7C61160398")
    )
    write(tmp_path, "acquisition.toml", content)

    config = load_acquisition(tmp_path)

    assert [(sensor.id, sensor.silo_id, sensor.leg) for sensor in config.temperature_sensors] == [
        (1, 1, 2),
        (2, None, None),
    ]


def test_configuration_without_temperature_sensors_is_valid(tmp_path: Path) -> None:
    write(tmp_path, "acquisition.toml", BASE_PLANT)

    assert load_acquisition(tmp_path).temperature_sensors == ()


@pytest.mark.parametrize(
    ("content", "message"),
    [
        pytest.param(
            sensor_block(1) + sensor_block(1, "28FF4A7C61160398"),
            "temperature_sensors[1].id: duplicate id '1'",
            id="duplicate-id",
        ),
        pytest.param(
            sensor_block(1) + sensor_block(2),
            "temperature_sensors[1].address: duplicate address '28A8F126AB240B1C'",
            id="duplicate-address",
        ),
        pytest.param(
            sensor_block(1, extra="silo_id = 9"),
            "temperature_sensors[0].silo_id: unknown silo 9",
            id="sensor-in-unknown-silo",
        ),
        pytest.param(
            sensor_block(1, extra="leg = 1"),
            "temperature_sensors[0].leg: leg requires a silo_id",
            id="leg-without-silo",
        ),
    ],
)
def test_invalid_temperature_sensor_layout_is_reported(
    tmp_path: Path, content: str, message: str
) -> None:
    write(tmp_path, "acquisition.toml", BASE_PLANT + content)

    assert errors_of(tmp_path) == [f"acquisition.toml: {message}"]


def test_temperature_sensors_without_board_are_reported(tmp_path: Path) -> None:
    plant = METER_BLOCK.format(id="m1", port="/a") + SILO_BLOCK.format(id=1, meter_id="m1")
    write(tmp_path, "acquisition.toml", plant + sensor_block(1))

    assert errors_of(tmp_path) == [
        "acquisition.toml: temperature_sensors: temperature sensors require a [board] section"
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("address", '"28a8f126ab240b1c"', id="lowercase-address"),
        pytest.param("address", '"28A8"', id="short-address"),
        pytest.param("id", "0", id="zero-id"),
        pytest.param("name", '""', id="empty-name"),
    ],
)
def test_invalid_temperature_sensor_field_is_rejected(
    tmp_path: Path, field: str, value: str
) -> None:
    lines = sensor_block(1).splitlines()
    content = "\n".join(
        f"{field} = {value}" if line.startswith(f"{field} =") else line for line in lines
    )
    write(tmp_path, "acquisition.toml", BASE_PLANT + content)

    (error,) = errors_of(tmp_path)

    assert error.startswith(f"acquisition.toml: temperature_sensors[0].{field}:")


@pytest.mark.parametrize("leg", ["0", "32768"])
def test_leg_outside_the_allowed_range_is_rejected(tmp_path: Path, leg: str) -> None:
    extra = f"silo_id = 1\nleg = {leg}"
    write(tmp_path, "acquisition.toml", BASE_PLANT + sensor_block(1, extra=extra))

    (error,) = errors_of(tmp_path)

    assert error.startswith("acquisition.toml: temperature_sensors[0].leg:")


def test_temperature_settings_have_defaults(tmp_path: Path) -> None:
    write(tmp_path, "acquisition.toml", BASE_PLANT)

    settings = load_acquisition(tmp_path).temperatures

    assert (settings.record_interval_s, settings.max_reading_age_s) == (1.0, 5.0)
    assert (settings.min_valid_c, settings.max_valid_c) == (-40.0, 80.0)


def test_temperature_settings_are_read_from_their_section(tmp_path: Path) -> None:
    section = (
        "\n[temperatures]\nrecord_interval_s = 10.0\nmax_reading_age_s = 3.0\n"
        "min_valid_c = -20.5\nmax_valid_c = 60.0\n"
    )
    write(tmp_path, "acquisition.toml", BASE_PLANT + section)

    settings = load_acquisition(tmp_path).temperatures

    assert (settings.record_interval_s, settings.max_reading_age_s) == (10.0, 3.0)
    assert (settings.min_valid_c, settings.max_valid_c) == (-20.5, 60.0)


@pytest.mark.parametrize(
    "line",
    [
        pytest.param("record_interval_s = 0", id="zero-interval"),
        pytest.param("max_reading_age_s = -1.0", id="negative-age"),
        pytest.param("min_valid_c = -1000.0", id="minimum-below-column-range"),
        pytest.param("max_valid_c = 1000.0", id="maximum-above-column-range"),
    ],
)
def test_invalid_temperature_setting_is_rejected(tmp_path: Path, line: str) -> None:
    write(tmp_path, "acquisition.toml", BASE_PLANT + f"\n[temperatures]\n{line}\n")

    (error,) = errors_of(tmp_path)

    assert error.startswith(f"acquisition.toml: temperatures.{line.split(' ', maxsplit=1)[0]}:")


def test_valid_range_with_minimum_not_below_maximum_is_reported(tmp_path: Path) -> None:
    section = "\n[temperatures]\nmin_valid_c = 30.0\nmax_valid_c = 30.0\n"
    write(tmp_path, "acquisition.toml", BASE_PLANT + section)

    assert errors_of(tmp_path) == [
        "acquisition.toml: temperatures.min_valid_c: must be below max_valid_c"
    ]
