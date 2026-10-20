import logging
import sys
from enum import StrEnum
from typing import TextIO

import structlog
from structlog.typing import Processor


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogFormat(StrEnum):
    AUTO = "auto"
    JSON = "json"
    CONSOLE = "console"


def configure_logging(
    level: LogLevel, log_format: LogFormat, stream: TextIO | None = None
) -> None:
    output = stream if stream is not None else sys.stdout
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
    )

    handler = logging.StreamHandler(output)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                *_renderers(log_format, output),
            ],
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.getLevelNamesMapping()[level.value])


def _renderers(log_format: LogFormat, output: TextIO) -> list[Processor]:
    use_console = log_format is LogFormat.CONSOLE or (
        log_format is LogFormat.AUTO and output.isatty()
    )
    if use_console:
        return [structlog.dev.ConsoleRenderer(colors=output.isatty())]
    return [structlog.processors.format_exc_info, structlog.processors.JSONRenderer()]
