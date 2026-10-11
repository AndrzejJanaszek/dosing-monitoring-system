import pytest

from dms.acquisition.main import main as acquisition_main


def test_stub_entry_point_fails_with_message(capsys: pytest.CaptureFixture[str]) -> None:
    assert acquisition_main() == 1
    assert "not implemented" in capsys.readouterr().err
