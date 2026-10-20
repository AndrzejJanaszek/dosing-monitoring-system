from pathlib import Path

from dms.config.loader import load_acquisition, load_shared
from dms.simulator.catalog import ONE_TANK_WITH_SENSORS
from dms.simulator.dms_config import acquisition_config

EXAMPLE_DIR = Path(__file__).parents[3] / "config" / "example"


def test_example_configuration_is_valid() -> None:
    shared = load_shared(EXAMPLE_DIR)
    acquisition = load_acquisition(EXAMPLE_DIR)

    assert shared.database.dbname == "dms"
    assert [silo.meter_id for silo in acquisition.silos] == [
        meter.id for meter in acquisition.meters
    ]


def test_example_acquisition_matches_the_simulator_layout() -> None:
    assert acquisition_config(ONE_TANK_WITH_SENSORS, Path("/tmp/dms")) == load_acquisition(
        EXAMPLE_DIR
    )
