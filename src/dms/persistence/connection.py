import time
from collections.abc import Callable

import psycopg
import structlog
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import TupleRow

from dms.clock import Clock, SystemClock
from dms.config.models import DatabaseConfig
from dms.logs import events
from dms.units import NS_PER_S

CONNECT_TIMEOUT_S = 30.0
CONNECT_ATTEMPT_TIMEOUT_S = 5
RETRY_INTERVAL_S = 1.0

logger = structlog.get_logger()


class DatabaseUnreachableError(Exception):
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
    *,
    timeout_s: float = CONNECT_TIMEOUT_S,
    retry_interval_s: float = RETRY_INTERVAL_S,
    sleep: Callable[[float], None] = time.sleep,
    clock: Clock | None = None,
) -> psycopg.Connection[TupleRow]:
    parameters = conninfo_to_dict(conninfo)
    role = parameters.get("user")
    clock = clock if clock is not None else SystemClock()
    retry_interval_ns = round(retry_interval_s * NS_PER_S)
    deadline_ns = clock.mono_ns() + round(timeout_s * NS_PER_S)
    attempt = 0
    while True:
        attempt += 1
        try:
            connection = psycopg.connect(conninfo, autocommit=True)
        except psycopg.OperationalError as error:
            if clock.mono_ns() + retry_interval_ns > deadline_ns:
                raise DatabaseUnreachableError(
                    f"database not reachable after {attempt} attempts: {error}"
                ) from error
            logger.warning(events.DB_CONNECT_RETRY, role=role, attempt=attempt, error=str(error))
            sleep(retry_interval_s)
            continue
        logger.info(events.DB_CONNECTED, role=role, dbname=parameters.get("dbname"))
        return connection
