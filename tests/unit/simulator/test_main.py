from pathlib import Path

import pytest

from dms.simulator.catalog import SCENARIOS
from dms.simulator.main import UNKNOWN_SCENARIO_EXIT_CODE, main


def test_list_prints_every_scenario(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list"]) == 0

    names = [line.split("\t")[0] for line in capsys.readouterr().out.splitlines()]
    assert names == list(SCENARIOS)


def test_config_prints_acquisition_toml(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["config", "dispense-single", "--link-dir", "/tmp/dms"]) == 0

    output = capsys.readouterr().out
    assert 'port = "/tmp/dms/meter-1"' in output
    assert 'meter_id = "meter-1"' in output


def test_unknown_scenario_lists_available_ones(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["config", "nope", "--link-dir", str(Path("/tmp/dms"))])

    assert exit_code == UNKNOWN_SCENARIO_EXIT_CODE
    error = capsys.readouterr().err
    assert "unknown scenario 'nope'" in error
    assert "dispense-single" in error
