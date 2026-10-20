from pathlib import Path

import pytest

from dms.acquisition.main import main
from dms.exit_codes import EXIT_CONFIG_ERROR


def test_missing_configuration_exits_with_config_error_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DMS_CONFIG_DIR", str(tmp_path))

    assert main() == EXIT_CONFIG_ERROR
    assert "shared.toml: file not found" in capsys.readouterr().err
