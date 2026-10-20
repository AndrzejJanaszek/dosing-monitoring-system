import json
from pathlib import Path

import pytest

from dms.exit_codes import EXIT_CONFIG_ERROR
from dms.logs import events
from dms.persistence.migrate import main


def test_missing_configuration_is_logged_and_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DMS_CONFIG_DIR", str(tmp_path))

    exit_code = main()

    captured = capsys.readouterr()
    log_entry = json.loads(captured.out.splitlines()[0])
    assert exit_code == EXIT_CONFIG_ERROR
    assert log_entry["event"] == events.CONFIG_INVALID
    assert log_entry["errors"]
    assert captured.err.strip()
