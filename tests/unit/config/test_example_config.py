from pathlib import Path

from dms.config.loader import load_acquisition, load_shared

EXAMPLE_DIR = Path(__file__).parents[3] / "config" / "example"


def test_example_configuration_is_valid() -> None:
    shared = load_shared(EXAMPLE_DIR)
    acquisition = load_acquisition(EXAMPLE_DIR)

    assert shared.database.dbname == "dms"
    assert [silo.meter for silo in acquisition.silos] == [meter.id for meter in acquisition.meters]
