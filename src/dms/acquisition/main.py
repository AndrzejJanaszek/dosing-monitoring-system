import signal
import sys
import threading
from functools import partial
from types import FrameType

import psycopg
import structlog

from dms.acquisition.app import AcquisitionApp, build_acquisition
from dms.acquisition.clock import SystemClock
from dms.acquisition.startup import run_startup_sequence
from dms.config.loader import ConfigError, load_acquisition, load_shared
from dms.logs import events
from dms.logs.setup import configure_logging
from dms.persistence.connection import StartupError, build_conninfo, connect_with_retry

WRITER_ROLE = "dms_writer"
EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_CONFIG_ERROR = 2


def _handle_signal(app: AcquisitionApp, _signal_number: int, _frame: FrameType | None) -> None:
    app.request_shutdown()


def _crash_hook(app: AcquisitionApp, arguments: threading.ExceptHookArgs) -> None:
    thread_name = arguments.thread.name if arguments.thread is not None else "unknown"
    structlog.get_logger().critical(
        events.THREAD_CRASHED, thread=thread_name, error=repr(arguments.exc_value)
    )
    app.fail()


def main() -> int:
    try:
        shared = load_shared()
        acquisition = load_acquisition()
    except ConfigError as error:
        configure_logging("INFO", "auto")
        structlog.get_logger().critical(events.CONFIG_INVALID, errors=error.errors)
        for line in error.errors:
            print(line, file=sys.stderr)
        return EXIT_CONFIG_ERROR
    configure_logging(shared.logging.level, shared.logging.format)
    logger = structlog.get_logger()

    conninfo = build_conninfo(shared.database, WRITER_ROLE)
    try:
        connection = connect_with_retry(conninfo)
    except StartupError as error:
        logger.critical(events.DB_STARTUP_FAILED, step="connect", error=str(error))
        return EXIT_FAILURE
    try:
        run_id = run_startup_sequence(connection, acquisition)
    except StartupError:
        return EXIT_FAILURE

    app = build_acquisition(
        config=acquisition,
        clock=SystemClock(),
        connection=connection,
        reconnect=lambda: psycopg.connect(conninfo, autocommit=True),
        run_id=run_id,
    )
    signal.signal(signal.SIGTERM, partial(_handle_signal, app))
    signal.signal(signal.SIGINT, partial(_handle_signal, app))
    previous_hook = threading.excepthook
    threading.excepthook = partial(_crash_hook, app)
    try:
        app.start()
        logger.info(events.SERVICE_STARTED, run_id=run_id)
        app.wait()
        app.stop()
    finally:
        threading.excepthook = previous_hook
    if app.failed:
        return EXIT_FAILURE
    logger.info(events.SERVICE_STOPPED, run_id=run_id)
    return EXIT_OK
