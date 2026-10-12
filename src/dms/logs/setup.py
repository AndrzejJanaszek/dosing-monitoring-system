import logging
import sys
from typing import Literal, TextIO

import structlog
from structlog.typing import Processor

type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
type LogFormat = Literal["auto", "json", "console"]


def configure_logging(level: LogLevel, log_format: LogFormat, stream: TextIO | None = None) -> None:
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
    root.setLevel(logging.getLevelNamesMapping()[level])


def _renderers(log_format: LogFormat, output: TextIO) -> list[Processor]:
    use_console = log_format == "console" or (log_format == "auto" and output.isatty())
    if use_console:
        return [structlog.dev.ConsoleRenderer(colors=output.isatty())]
    return [structlog.processors.format_exc_info, structlog.processors.JSONRenderer()]
