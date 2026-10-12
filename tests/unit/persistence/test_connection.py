from psycopg.conninfo import conninfo_to_dict

from dms.config.models import DatabaseConfig
from dms.persistence.connection import CONNECT_ATTEMPT_TIMEOUT_S, build_conninfo


def test_conninfo_limits_a_single_connection_attempt() -> None:
    parameters = conninfo_to_dict(build_conninfo(DatabaseConfig(), "dms_writer"))

    assert parameters["user"] == "dms_writer"
    assert parameters["connect_timeout"] == str(CONNECT_ATTEMPT_TIMEOUT_S)
