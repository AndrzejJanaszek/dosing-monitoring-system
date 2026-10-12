import time
from collections.abc import Callable

import psycopg
import structlog
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import TupleRow

from dms.config.models import DatabaseConfig
from dms.logs import events

CONNECT_TIMEOUT_S = 30.0
CONNECT_ATTEMPT_TIMEOUT_S = 5
RETRY_INTERVAL_S = 1.0


class StartupError(Exception):
    pass


def build_conninfo(database: DatabaseConfig, role: str) -> str:
    return make_conninfo(
        host=database.host,
        port=database.port,
        dbname=database.dbname,
        user=role,
        connect_timeout=CONNECT_ATTEMPT_TIMEOUT_S,
    )


def connect_with_retry(
    conninfo: str,
    timeout_s: float = CONNECT_TIMEOUT_S,
    retry_interval_s: float = RETRY_INTERVAL_S,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> psycopg.Connection[TupleRow]:
    logger = structlog.get_logger()
    parameters = conninfo_to_dict(conninfo)
    role = parameters.get("user")
    deadline = monotonic() + timeout_s
    attempt = 0
    while True:
        attempt += 1
        try:
            connection = psycopg.connect(conninfo, autocommit=True)
        except psycopg.OperationalError as error:
            if monotonic() + retry_interval_s > deadline:
                raise StartupError(
                    f"database not reachable after {attempt} attempts: {error}"
                ) from error
            logger.warning(events.DB_CONNECT_RETRY, role=role, attempt=attempt, error=str(error))
            sleep(retry_interval_s)
            continue
        logger.info(events.DB_CONNECTED, role=role, dbname=parameters.get("dbname"))
        return connection
