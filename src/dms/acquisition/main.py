import signal
import sys
import threading
from functools import partial
from types import FrameType

import psycopg
import structlog

from dms.acquisition.app import AcquisitionApp, build_acquisition
from dms.acquisition.startup import StartupError, run_startup_sequence
from dms.clock import SystemClock
from dms.config.loader import ConfigError, load_acquisition, load_shared
from dms.exit_codes import EXIT_CONFIG_ERROR, EXIT_FAILURE, EXIT_OK
from dms.logs import events
from dms.logs.setup import LogFormat, LogLevel, configure_logging
from dms.persistence.connection import (
    DatabaseUnreachableError,
    build_conninfo,
    connect_with_retry,
)

WRITER_ROLE = "dms_writer"

logger = structlog.get_logger()


def _handle_signal(app: AcquisitionApp, _signal_number: int, _frame: FrameType | None) -> None:
    app.request_shutdown()


def _crash_hook(app: AcquisitionApp, arguments: threading.ExceptHookArgs) -> None:
    thread_name = arguments.thread.name if arguments.thread is not None else "unknown"
    logger.critical(
        events.THREAD_CRASHED,
        thread=thread_name,
        error=str(arguments.exc_value),
        exc_info=arguments.exc_value,
    )
    app.fail()


def main() -> int:
    try:
        shared_config = load_shared()
        acquisition_config = load_acquisition()
    except ConfigError as error:
        configure_logging(LogLevel.INFO, LogFormat.AUTO)
        logger.critical(events.CONFIG_INVALID, errors=error.errors)
        for line in error.errors:
            print(line, file=sys.stderr)
        return EXIT_CONFIG_ERROR
    configure_logging(shared_config.logging.level, shared_config.logging.format)

    conninfo = build_conninfo(shared_config.database, WRITER_ROLE)
    try:
        connection = connect_with_retry(conninfo)
    except DatabaseUnreachableError as error:
        logger.critical(events.DB_STARTUP_FAILED, step="connect", error=str(error))
        return EXIT_FAILURE
    try:
        started_run = run_startup_sequence(connection, acquisition_config)
    except StartupError:
        return EXIT_FAILURE
    run_id = started_run.run_id

    app = build_acquisition(
        config=acquisition_config,
        clock=SystemClock(),
        connection=connection,
        reconnect=lambda: psycopg.connect(conninfo, autocommit=True),
        run_id=run_id,
        rate_samples=started_run.rate_samples,
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
