from collections.abc import Callable

import pytest

from dms.acquisition.main import main as acquisition_main
from dms.persistence.migrate import main as migrate_main


@pytest.mark.parametrize("entry_point", [acquisition_main, migrate_main])
def test_stub_entry_point_fails_with_message(
    entry_point: Callable[[], int], capsys: pytest.CaptureFixture[str]
) -> None:
    assert entry_point() == 1
    assert "not implemented" in capsys.readouterr().err
